"""Advanced settings workflows for the coordinator."""

from __future__ import annotations

from collections.abc import Callable, Mapping, MutableMapping
from dataclasses import replace
from typing import Any

from ..activity_alerts import ActivityAlertSettings
from ..alert_feedback import (
    alert_feedback_is_expired,
    alert_feedback_status,
    mapping_datetime,
)
from ..alerting import ConservativeAlertPolicy
from ..balance import DEFAULT_BALANCE_NEGATIVE_TOLERANCE_W
from ..billing import BillingCycleSettings
from ..capacity import DEFAULT_CAPACITY_WARNING_RATIO, CapacitySettings
from ..const import (
    CONF_ADVANCED_SETTINGS,
    CONF_SENSITIVITY,
    CONF_UTILITY_COMPARISON_SETTINGS,
    DEFAULT_SENSITIVITY,
)
from ..cost import CostSettings
from ..cycles import (
    MIN_CYCLE_BASELINE_CONFIDENCE,
    RUN_CYCLE_DURATION_FEATURE,
    cycle_baseline_feature_values,
)
from ..demand import DemandSettings
from ..goals import EnergyGoalSettings
from ..load_shift import FLEXIBLE_LOAD_RUNNING_THRESHOLD_W
from ..metric_consistency import (
    DEFAULT_APPARENT_POWER_TOLERANCE_PERCENT,
    DEFAULT_MIN_APPARENT_POWER_VA,
    DEFAULT_POWER_FACTOR_TOLERANCE,
)
from ..models import EventType
from ..operating_detection import (
    OPERATING_DETECTION_OVERRIDE_FIELDS,
    OPERATING_DETECTION_SOURCE,
    OperatingThresholdSource,
    resolve_operating_detection_from_settings,
)
from ..phase_balance import (
    DEFAULT_LEG_IMBALANCE_MIN_TOTAL_POWER_W,
    DEFAULT_LEG_IMBALANCE_WARNING_RATIO,
)
from ..recommendation_guidance import recommendation_setting_default_value
from ..settings_advisor import (
    DEFAULT_RECOMMENDATION_TTL,
    AdvisorCircuitContext,
    AdvisorInputs,
    RecommendationDecision,
    RecommendationStatus,
    SettingRecommendation,
    build_settings_recommendations,
    recommendation_evidence_fingerprint,
    recommendation_id_for,
    recommendation_to_dict,
    recommendation_unique_key,
    should_suppress_recommendation,
)
from ..solar_flow import (
    EXPORT_TOLERANCE_W,
    HIGH_SOLAR_SURPLUS_THRESHOLD_W,
    SOLAR_SURPLUS_THRESHOLD_W,
)
from ..standby import StandbySettings
from ..usage import EnergyUsageSettings
from ..utility_comparison import (
    DEFAULT_UTILITY_COMPARISON_TOLERANCE_PERCENT,
    DEFAULT_UTILITY_STATISTIC_PERIOD,
    UtilityComparisonSettings,
)
from ..ux import alert_policy_name_for_sensitivity, normalize_sensitivity

ALERT_UNHELPFUL_RECOMMENDATION_MIN_COUNT = 2


class SettingsController:
    """Own user-triggered advanced setting recommendation actions."""

    def __init__(self, coordinator: Any) -> None:
        self._coordinator = coordinator
        self._alert_policies: dict[tuple[str, str], ConservativeAlertPolicy] = {}
        self._usage_alert_policies: dict[tuple[str, str], ConservativeAlertPolicy] = {}
        self._goal_alert_policies: dict[tuple[str, str], ConservativeAlertPolicy] = {}
        self._billing_alert_policies: dict[
            tuple[str, str],
            ConservativeAlertPolicy,
        ] = {}
        self._demand_alert_policies: dict[tuple[str, str], ConservativeAlertPolicy] = {}
        self._capacity_alert_policies: dict[
            tuple[str, str],
            ConservativeAlertPolicy,
        ] = {}
        self._leg_imbalance_alert_policies: dict[
            tuple[str, str],
            ConservativeAlertPolicy,
        ] = {}
        self._standby_alert_policies: dict[
            tuple[str, str],
            ConservativeAlertPolicy,
        ] = {}
        self._utility_comparison_alert_policies: dict[
            tuple[str, str],
            ConservativeAlertPolicy,
        ] = {}
        self._nilm_topology_alert_policies: dict[
            tuple[str, str],
            ConservativeAlertPolicy,
        ] = {}
        self._cycle_alert_policies: dict[tuple[str, str], ConservativeAlertPolicy] = {}
        self._activity_alert_policies: dict[
            tuple[str, str],
            ConservativeAlertPolicy,
        ] = {}
        self._water_context_alert_policies: dict[
            tuple[str, str, str],
            ConservativeAlertPolicy,
        ] = {}

    async def async_recalculate_setting_recommendations(
        self,
        circuit_id: str | None = None,
    ) -> None:
        """Rebuild pending advanced-setting recommendations from retained data."""
        coordinator = self._coordinator
        now = coordinator._now_fn()
        if self.rebuild_setting_recommendations(now, circuit_id=circuit_id):
            coordinator.store_persistence.mark_dirty()
        coordinator.async_set_updated_data(coordinator.state)
        await coordinator.store_persistence.async_save_if_dirty(now)
        await (
            coordinator.notification_controller.async_notify_settings_recommendations_if_needed()
        )

    def rebuild_setting_recommendations(
        self,
        now: Any,
        *,
        circuit_id: str | None = None,
    ) -> bool:
        """Rebuild pending recommendations without saving or notifying."""
        coordinator = self._coordinator
        target_configs = [
            config
            for config in coordinator.circuit_configs
            if circuit_id is None or config.circuit_id == circuit_id
        ]
        changed = False

        for config in target_configs:
            advisor_inputs = self.advisor_inputs_for_config(config, now)
            recommendations = build_settings_recommendations(advisor_inputs)
            recommendations.extend(
                self.unhelpful_alert_setting_recommendations(
                    config,
                    now,
                    existing_recommendation_ids={
                        recommendation.recommendation_id
                        for recommendation in recommendations
                    },
                ),
            )
            recommendation_ids = {
                recommendation.recommendation_id
                for recommendation in recommendations
            }
            for stored_id, stored in list(
                coordinator.store_data.settings_recommendations.items(),
            ):
                if (
                    stored.circuit_id == config.circuit_id
                    and stored.status is RecommendationStatus.PENDING
                    and stored_id not in recommendation_ids
                ):
                    coordinator.store_data.settings_recommendations[stored_id] = (
                        replace(
                            stored,
                            status=RecommendationStatus.STALE,
                        )
                    )
                    changed = True

            for recommendation in recommendations:
                stored = coordinator.store_data.settings_recommendations.get(
                    recommendation.recommendation_id,
                )
                if (
                    stored is not None
                    and stored.status is RecommendationStatus.PENDING
                    and stored.expires_at > now
                    and _recommendation_materially_matches(stored, recommendation)
                ):
                    continue
                if stored != recommendation:
                    coordinator.store_data.settings_recommendations[
                        recommendation.recommendation_id
                    ] = recommendation
                    changed = True

        self.refresh_settings_recommendation_state(now)
        return changed

    def advisor_inputs_for_config(
        self,
        config: Any,
        now: Any,
    ) -> AdvisorInputs:
        """Build settings-advisor input payloads for one circuit."""
        coordinator = self._coordinator
        return AdvisorInputs(
            now=now,
            context=AdvisorCircuitContext(
                circuit_id=config.circuit_id,
                circuit_name=config.name,
                appliance_profile=config.appliance_profile.value,
                circuit_mode=config.mode.value,
                power_flow=config.power_flow.value,
                advanced_settings=self.advanced_settings_for_circuit(config.circuit_id),
            ),
            feature_history=self.advisor_feature_history_for_circuit(
                config,
                now,
            ),
            decisions=coordinator.store_data.settings_recommendation_decisions,
        )

    def advisor_feature_history_for_circuit(
        self,
        config: Any,
        now: Any,
    ) -> dict[str, Any]:
        """Build retained feature history used by settings recommendations."""
        coordinator = self._coordinator
        circuit_id = config.circuit_id
        feature_history: dict[str, Any] = {
            "energy_usage_days": [],
            "cycles": [],
            "operating_idle_samples": [],
            "operating_start_samples": [],
            "standby_samples_w": [],
            "current_samples": [],
            "leg_imbalance_ratios": [],
            "dual_phase_total_power_w": [],
            "apparent_power_residual_percent": [],
            "power_factor_residual": [],
            "apparent_power_samples_va": [],
            "negative_balance_w": [],
            "solar_export_w": [],
        }

        usage_history = coordinator.store_data.energy_usage_by_circuit.get(
            circuit_id,
            {},
        )
        usage_days = usage_history.get("days")
        if isinstance(usage_days, list):
            feature_history["energy_usage_days"] = list(usage_days)

        merge_gap_seconds = resolve_operating_detection_from_settings(
            config,
            getattr(
                coordinator.store_data,
                "operating_detection_settings_by_circuit",
                {},
            ).get(circuit_id, {}),
        ).profile.merge_gap_seconds
        cycle_values = cycle_baseline_feature_values(
            coordinator.store_data.events,
            circuit_id=circuit_id,
            now=now,
            merge_gap_seconds=merge_gap_seconds,
            time_zone=coordinator.context_builder.time_zone(),
        )
        feature_history["cycles"] = [
            {"duration_minutes": duration_seconds / 60.0}
            for duration_seconds in _numeric_items(
                cycle_values.get(RUN_CYCLE_DURATION_FEATURE, []),
            )
        ]

        standby_history = coordinator.store_data.standby_by_circuit.get(
            circuit_id,
            {},
        )
        standby_samples = standby_history.get("samples")
        if isinstance(standby_samples, list):
            feature_history["operating_idle_samples"] = [
                dict(sample)
                for sample in standby_samples
                if isinstance(sample, Mapping)
            ]
        feature_history["standby_samples_w"] = _numeric_items(
            standby_samples,
            keys=("real_power_w",),
        )

        feature_history["operating_start_samples"] = [
            {
                "timestamp": event.timestamp.isoformat(),
                "power_w": float(event.features["startup_power_w"]),
            }
            for event in coordinator.store_data.events
            if (
                event.circuit_id == circuit_id
                and event.event_type is EventType.START
                and "startup_power_w" in event.features
            )
        ]

        demand_history = coordinator.store_data.demand_by_circuit.get(circuit_id, {})
        feature_history["current_samples"] = _numeric_items(
            demand_history.get("capacity_current_samples"),
            keys=("current_amps", "current_a", "amps"),
        )
        feature_history["current_samples"].extend(
            _numeric_items(
                demand_history.get("samples"),
                keys=("current_a", "current_amps", "amps"),
            )
        )

        leg_evidence = coordinator.state.leg_imbalance_evidence_by_circuit.get(
            circuit_id,
            {},
        )
        feature_history["leg_imbalance_ratios"] = _numeric_items(
            [leg_evidence],
            keys=("leg_imbalance_ratio",),
        )
        total_power = _sum_optional_values(
            leg_evidence.get("left_real_power_w"),
            leg_evidence.get("right_real_power_w"),
        )
        if total_power is not None:
            feature_history["dual_phase_total_power_w"] = [total_power]

        metric_evidence = coordinator.state.metric_consistency_evidence_by_circuit.get(
            circuit_id,
            {},
        )
        feature_history["apparent_power_residual_percent"] = _numeric_items(
            [metric_evidence],
            keys=("apparent_power_difference_percent",),
        )
        feature_history["power_factor_residual"] = _numeric_items(
            [metric_evidence],
            keys=("power_factor_difference",),
        )
        feature_history["apparent_power_samples_va"] = _numeric_items(
            [metric_evidence],
            keys=("reported_apparent_power_va",),
        )

        balance_evidence = coordinator.state.balance_evidence_by_circuit.get(
            circuit_id,
            {},
        )
        feature_history["negative_balance_w"] = _numeric_items(
            [balance_evidence],
            keys=("balance_power_w",),
        )

        solar_evidence = coordinator.state.solar_flow_evidence_by_circuit.get(
            circuit_id,
            {},
        )
        feature_history["solar_export_w"] = _numeric_items(
            [solar_evidence],
            keys=("grid_export_w", "solar_grid_export_w"),
        )

        return feature_history

    def unhelpful_alert_setting_recommendations(
        self,
        config: Any,
        now: Any,
        *,
        existing_recommendation_ids: set[str],
    ) -> list[SettingRecommendation]:
        """Build recommendations from repeated unhelpful daily-spike feedback."""
        coordinator = self._coordinator
        recommendation_id = recommendation_id_for(
            config.circuit_id,
            "daily_spike_ratio",
        )
        if recommendation_id in existing_recommendation_ids:
            return []

        feedback = self.repeated_unhelpful_daily_spike_feedback(config, now)
        if feedback is None:
            return []

        advanced_settings = self.advanced_settings_for_circuit(config.circuit_id)
        current_value = _positive_float_value(
            advanced_settings.get("daily_spike_ratio"),
            default=config.daily_energy_spike_ratio,
        )
        change_ratio = _absolute_float_value(feedback.get("change_ratio"))
        suggested_value = round(
            min(1.0, max(current_value + 0.05, change_ratio + 0.10)),
            1,
        )
        if suggested_value <= current_value:
            return []

        unique_key = recommendation_unique_key(config.circuit_id, "daily_spike_ratio")
        evidence = {
            "source": "unhelpful_alert_feedback",
            "feedback_fingerprint": str(feedback.get("fingerprint") or ""),
            "unhelpful_feedback_count": _positive_int_value(
                feedback.get("evidence_count"),
                default=1,
            ),
            "change_ratio": round(change_ratio, 3),
            "observed_value": _optional_float_value(feedback.get("observed_value")),
            "baseline_value": _optional_float_value(feedback.get("baseline_value")),
            "suggested_daily_spike_ratio": suggested_value,
        }
        recommendation = SettingRecommendation(
            recommendation_id=recommendation_id,
            unique_key=unique_key,
            circuit_id=config.circuit_id,
            circuit_name=config.name,
            setting_key="daily_spike_ratio",
            setting_label="Daily Spike Ratio",
            current_value=current_value,
            suggested_value=suggested_value,
            unit="ratio",
            feature="energy_usage_spikes",
            group="Energy Usage",
            confidence=0.72,
            reason=(
                "This daily energy spike pattern was repeatedly marked not "
                "helpful. Increase the daily spike ratio to make future "
                "matching alerts more conservative."
            ),
            evidence=evidence,
            apply_payload={"daily_spike_ratio": suggested_value},
            status=RecommendationStatus.PENDING,
            created_at=now,
            expires_at=now + DEFAULT_RECOMMENDATION_TTL,
        )
        if should_suppress_recommendation(
            coordinator.store_data.settings_recommendation_decisions.get(unique_key),
            now=now,
            suggested_value=recommendation.suggested_value,
            evidence_fingerprint=recommendation_evidence_fingerprint(recommendation),
        ):
            return []
        return [recommendation]

    def repeated_unhelpful_daily_spike_feedback(
        self,
        config: Any,
        now: Any,
    ) -> Mapping[str, Any] | None:
        """Return the best repeated unhelpful daily-spike feedback for a circuit."""
        matches: list[Mapping[str, Any]] = []
        for feedback in self._coordinator.store_data.alert_feedback.values():
            if not isinstance(feedback, Mapping):
                continue
            if alert_feedback_status(feedback) != "unhelpful":
                continue
            if alert_feedback_is_expired(feedback, now):
                continue
            if str(feedback.get("circuit_id") or "") != config.circuit_id:
                continue
            if str(feedback.get("feature") or "") != "daily_energy_usage_spike":
                continue
            if (
                _positive_int_value(feedback.get("evidence_count"), default=1)
                < ALERT_UNHELPFUL_RECOMMENDATION_MIN_COUNT
            ):
                continue
            matches.append(feedback)
        if not matches:
            return None
        return max(
            matches,
            key=lambda feedback: (
                _positive_int_value(feedback.get("evidence_count"), default=1),
                (
                    mapping_datetime(feedback.get("last_seen")).timestamp()
                    if mapping_datetime(feedback.get("last_seen")) is not None
                    else 0.0
                ),
            ),
        )

    async def async_replace_advanced_settings(
        self,
        circuit_id: str,
        settings: Mapping[str, Any],
    ) -> None:
        """Replace store-backed advanced settings for one circuit."""
        coordinator = self._coordinator
        advanced_by_circuit = coordinator.options.setdefault(
            CONF_ADVANCED_SETTINGS,
            {},
        )
        if not isinstance(advanced_by_circuit, dict):
            advanced_by_circuit = dict(advanced_by_circuit)
            coordinator.options[CONF_ADVANCED_SETTINGS] = advanced_by_circuit
        updated_settings = dict(settings)
        advanced_by_circuit[circuit_id] = updated_settings
        self.replace_advanced_settings(circuit_id, updated_settings)
        coordinator.store_persistence.mark_dirty()
        now = coordinator._now_fn()
        coordinator._refresh_ux_state_for_circuit(circuit_id, now)
        coordinator.async_set_updated_data(coordinator.state)
        await coordinator.store_persistence.async_save_if_dirty(now)

    def apply_config_entry_settings(self) -> None:
        """Apply setup/options settings to store-backed runtime setting maps."""
        coordinator = self._coordinator
        for circuit_id, settings in _merged_entry_settings_map(
            coordinator.entry_data,
            coordinator.options,
            CONF_UTILITY_COMPARISON_SETTINGS,
        ).items():
            if settings:
                coordinator.store_data.utility_comparison_settings_by_circuit[
                    circuit_id
                ] = settings
            else:
                coordinator.store_data.utility_comparison_settings_by_circuit.pop(
                    circuit_id,
                    None,
                )

        for circuit_id, settings in _merged_entry_settings_map(
            coordinator.entry_data,
            coordinator.options,
            CONF_ADVANCED_SETTINGS,
        ).items():
            self.replace_advanced_settings(circuit_id, settings)

    async def async_set_circuit_sensitivity(
        self,
        circuit_id: str,
        preset: str,
    ) -> None:
        """Persist an alert sensitivity preset for one circuit."""
        await self._async_save_circuit_settings(
            circuit_id,
            self._coordinator.store_data.sensitivity_by_circuit,
            normalize_sensitivity(preset),
        )

    @property
    def default_sensitivity(self) -> str:
        """Return the normalized default alert sensitivity."""
        coordinator = self._coordinator
        return normalize_sensitivity(
            coordinator.options.get(
                CONF_SENSITIVITY,
                coordinator.entry_data.get(CONF_SENSITIVITY, DEFAULT_SENSITIVITY),
            )
        )

    def sensitivity_for_circuit(self, circuit_id: str) -> str:
        """Return normalized alert sensitivity for one circuit."""
        return normalize_sensitivity(
            self._coordinator.store_data.sensitivity_by_circuit.get(
                circuit_id,
                self.default_sensitivity,
            )
        )

    def alert_policy_for_circuit(self, circuit_id: str) -> ConservativeAlertPolicy:
        """Return the default alert policy for one circuit."""
        policy_name = self._alert_policy_name_for_circuit(circuit_id)
        return self._cached_alert_policy(
            self._alert_policies,
            (circuit_id, policy_name),
            lambda: _alert_policy_for_sensitivity(policy_name),
        )

    def usage_alert_policy_for_circuit(
        self,
        circuit_id: str,
    ) -> ConservativeAlertPolicy:
        """Return the daily usage spike alert policy for one circuit."""
        return self._repeated_alert_policy_for_circuit(
            self._usage_alert_policies,
            circuit_id,
            min_baseline_confidence=0.8,
        )

    def goal_alert_policy_for_circuit(
        self,
        circuit_id: str,
    ) -> ConservativeAlertPolicy:
        """Return the daily energy goal alert policy for one circuit."""
        return self._repeated_alert_policy_for_circuit(
            self._goal_alert_policies,
            circuit_id,
            min_baseline_confidence=1.0,
        )

    def billing_alert_policy_for_circuit(
        self,
        circuit_id: str,
    ) -> ConservativeAlertPolicy:
        """Return the billing-cycle budget alert policy for one circuit."""
        return self._repeated_alert_policy_for_circuit(
            self._billing_alert_policies,
            circuit_id,
            min_baseline_confidence=1.0,
        )

    def demand_alert_policy_for_circuit(
        self,
        circuit_id: str,
    ) -> ConservativeAlertPolicy:
        """Return the demand alert policy for one circuit."""
        return self._repeated_alert_policy_for_circuit(
            self._demand_alert_policies,
            circuit_id,
            min_baseline_confidence=1.0,
        )

    def capacity_alert_policy_for_circuit(
        self,
        circuit_id: str,
    ) -> ConservativeAlertPolicy:
        """Return the capacity alert policy for one circuit."""
        return self._repeated_alert_policy_for_circuit(
            self._capacity_alert_policies,
            circuit_id,
            min_baseline_confidence=1.0,
        )

    def leg_imbalance_alert_policy_for_circuit(
        self,
        circuit_id: str,
    ) -> ConservativeAlertPolicy:
        """Return the leg imbalance alert policy for one circuit."""
        return self._repeated_alert_policy_for_circuit(
            self._leg_imbalance_alert_policies,
            circuit_id,
            min_baseline_confidence=1.0,
        )

    def standby_alert_policy_for_circuit(
        self,
        circuit_id: str,
    ) -> ConservativeAlertPolicy:
        """Return the standby alert policy for one circuit."""
        return self._repeated_alert_policy_for_circuit(
            self._standby_alert_policies,
            circuit_id,
            min_baseline_confidence=1.0,
        )

    def utility_comparison_alert_policy_for_circuit(
        self,
        circuit_id: str,
    ) -> ConservativeAlertPolicy:
        """Return the utility comparison alert policy for one circuit."""
        return self._repeated_alert_policy_for_circuit(
            self._utility_comparison_alert_policies,
            circuit_id,
            min_baseline_confidence=1.0,
        )

    def nilm_topology_alert_policy_for_circuit(
        self,
        circuit_id: str,
    ) -> ConservativeAlertPolicy:
        """Return the NILM topology alert policy for one circuit."""
        return self._repeated_alert_policy_for_circuit(
            self._nilm_topology_alert_policies,
            circuit_id,
            min_baseline_confidence=1.0,
        )

    def cycle_alert_policy_for_circuit(
        self,
        circuit_id: str,
    ) -> ConservativeAlertPolicy:
        """Return the run-cycle alert policy for one circuit."""
        return self._repeated_alert_policy_for_circuit(
            self._cycle_alert_policies,
            circuit_id,
            min_baseline_confidence=MIN_CYCLE_BASELINE_CONFIDENCE,
            min_total_score_multiplier=1.5,
            min_average_score=1.5,
        )

    def activity_alert_policy_for_circuit(
        self,
        circuit_id: str,
    ) -> ConservativeAlertPolicy:
        """Return the configured activity alert policy for one circuit."""
        return self._repeated_alert_policy_for_circuit(
            self._activity_alert_policies,
            circuit_id,
            min_baseline_confidence=1.0,
        )

    def water_context_alert_policy_for_circuit(
        self,
        circuit_id: str,
        feature: str,
    ) -> ConservativeAlertPolicy:
        """Return the water context alert policy for one circuit feature."""
        policy_name = self._alert_policy_name_for_circuit(circuit_id)
        key = (circuit_id, feature, policy_name)
        return self._cached_alert_policy(
            self._water_context_alert_policies,
            key,
            lambda: self._repeated_alert_policy(
                policy_name,
                min_baseline_confidence=0.7,
            ),
        )

    def nilm_min_delta_w(self, circuit_id: str) -> float:
        """Return the NILM edge detector minimum delta for one circuit."""
        policy_name = self._alert_policy_name_for_circuit(circuit_id)
        if policy_name == "high":
            return 75.0
        if policy_name == "low":
            return 150.0
        return 100.0

    def clear_nilm_topology_alert_policies(self, circuit_id: str) -> None:
        """Clear cached NILM topology policies for one circuit."""
        for key in list(self._nilm_topology_alert_policies):
            if key[0] == circuit_id:
                self._nilm_topology_alert_policies.pop(key, None)

    def _alert_policy_name_for_circuit(self, circuit_id: str) -> str:
        return alert_policy_name_for_sensitivity(
            self.sensitivity_for_circuit(circuit_id)
        )

    @staticmethod
    def _cached_alert_policy(
        cache: MutableMapping[tuple[str, ...], ConservativeAlertPolicy],
        key: tuple[str, ...],
        factory: Callable[[], ConservativeAlertPolicy],
    ) -> ConservativeAlertPolicy:
        policy = cache.get(key)
        if policy is None:
            policy = factory()
            cache[key] = policy
        return policy

    def _repeated_alert_policy_for_circuit(
        self,
        cache: MutableMapping[tuple[str, str], ConservativeAlertPolicy],
        circuit_id: str,
        *,
        min_baseline_confidence: float,
        min_total_score_multiplier: float = 1.0,
        min_average_score: float = 1.0,
    ) -> ConservativeAlertPolicy:
        policy_name = self._alert_policy_name_for_circuit(circuit_id)
        return self._cached_alert_policy(
            cache,
            (circuit_id, policy_name),
            lambda: self._repeated_alert_policy(
                policy_name,
                min_baseline_confidence=min_baseline_confidence,
                min_total_score_multiplier=min_total_score_multiplier,
                min_average_score=min_average_score,
            ),
        )

    @staticmethod
    def _repeated_alert_policy(
        policy_name: str,
        *,
        min_baseline_confidence: float,
        min_total_score_multiplier: float = 1.0,
        min_average_score: float = 1.0,
    ) -> ConservativeAlertPolicy:
        min_repeated = 4 if policy_name == "low" else 3
        return ConservativeAlertPolicy(
            min_repeated=min_repeated,
            min_total_score=min_repeated * min_total_score_multiplier,
            min_average_score=min_average_score,
            min_baseline_confidence=min_baseline_confidence,
        )

    def activity_alert_settings_for_config(
        self,
        config: Any | None,
        circuit_id: str,
    ) -> ActivityAlertSettings:
        """Return activity alert settings for one circuit."""
        del config
        overrides = (
            self._coordinator.store_data.activity_alert_settings_by_circuit.get(
                circuit_id,
                {},
            )
        )
        return ActivityAlertSettings(
            max_active_minutes=_optional_positive_float_value(
                overrides.get("max_active_minutes"),
                default=None,
            ),
            max_idle_minutes=_optional_positive_float_value(
                overrides.get("max_idle_minutes"),
                default=None,
            ),
        )

    def energy_usage_settings_for_config(
        self,
        config: Any | None,
        circuit_id: str,
    ) -> EnergyUsageSettings:
        """Return daily energy usage spike settings for one circuit."""
        overrides = (
            self._coordinator.store_data.energy_usage_settings_by_circuit.get(
                circuit_id,
                {},
            )
        )
        default_window_days = (
            config.energy_usage_window_days if config is not None else 7
        )
        default_spike_ratio = (
            config.daily_energy_spike_ratio if config is not None else 0.25
        )
        return EnergyUsageSettings(
            window_days=_positive_int_value(
                overrides.get("window_days"),
                default=default_window_days,
            ),
            daily_spike_ratio=_positive_float_value(
                overrides.get("daily_spike_ratio"),
                default=default_spike_ratio,
            ),
        )

    def energy_goal_settings_for_config(
        self,
        config: Any | None,
        circuit_id: str,
    ) -> EnergyGoalSettings:
        """Return daily energy goal settings for one circuit."""
        overrides = (
            self._coordinator.store_data.energy_goal_settings_by_circuit.get(
                circuit_id,
                {},
            )
        )
        default_goal_kwh = (
            config.daily_energy_goal_kwh if config is not None else None
        )
        default_alert_ratio = (
            config.energy_goal_alert_ratio if config is not None else 1.0
        )
        if "daily_goal_kwh" in overrides:
            goal_kwh = _optional_positive_float_value(
                overrides.get("daily_goal_kwh"),
                default=None,
            )
        else:
            goal_kwh = default_goal_kwh
        return EnergyGoalSettings(
            daily_goal_kwh=goal_kwh,
            goal_alert_ratio=_positive_float_value(
                overrides.get("goal_alert_ratio"),
                default=default_alert_ratio,
            ),
        )

    def billing_cycle_settings_for_config(
        self,
        config: Any | None,
        circuit_id: str,
    ) -> BillingCycleSettings:
        """Return billing-cycle usage forecast settings for one circuit."""
        overrides = self._coordinator.store_data.billing_settings_by_circuit.get(
            circuit_id,
            {},
        )
        default_start_day = (
            config.billing_cycle_start_day if config is not None else 1
        )
        default_budget_kwh = (
            config.billing_cycle_budget_kwh if config is not None else None
        )
        default_alert_ratio = (
            config.billing_cycle_budget_alert_ratio if config is not None else 1.0
        )
        default_min_elapsed_days = (
            config.billing_cycle_min_elapsed_days if config is not None else 3
        )
        return BillingCycleSettings(
            cycle_start_day=_positive_int_value(
                overrides.get("cycle_start_day"),
                default=default_start_day,
            ),
            budget_kwh=_optional_positive_float_value(
                overrides.get("budget_kwh"),
                default=default_budget_kwh,
            ),
            budget_alert_ratio=_positive_float_value(
                overrides.get("budget_alert_ratio"),
                default=default_alert_ratio,
            ),
            min_elapsed_days=_positive_int_value(
                overrides.get("min_elapsed_days"),
                default=default_min_elapsed_days,
            ),
        )

    def cost_settings_for_config(
        self,
        config: Any | None,
        circuit_id: str,
    ) -> CostSettings:
        """Return cost and Time-of-Use settings for one circuit."""
        overrides = self._coordinator.store_data.cost_settings_by_circuit.get(
            circuit_id,
            {},
        )
        default_start_day = config.cost_cycle_start_day if config is not None else 1
        default_rate = config.default_rate_per_kwh if config is not None else None
        default_tou_rate = config.tou_rate_per_kwh if config is not None else None
        default_tou_start = config.tou_start if config is not None else None
        default_tou_end = config.tou_end if config is not None else None
        default_tou_weekdays = config.tou_weekdays if config is not None else ()
        default_tou_name = config.tou_name if config is not None else "Peak"
        return CostSettings(
            cycle_start_day=_positive_int_value(
                overrides.get("cycle_start_day"),
                default=default_start_day,
            ),
            default_rate_per_kwh=_optional_positive_float_value(
                overrides.get("default_rate_per_kwh"),
                default=default_rate,
            ),
            tou_rate_per_kwh=_optional_positive_float_value(
                overrides.get("tou_rate_per_kwh"),
                default=default_tou_rate,
            ),
            tou_start=str(overrides.get("tou_start") or default_tou_start or ""),
            tou_end=str(overrides.get("tou_end") or default_tou_end or ""),
            tou_weekdays=_weekday_tuple_value(
                overrides.get("tou_weekdays"),
                default=default_tou_weekdays,
            ),
            tou_name=str(overrides.get("tou_name") or default_tou_name or "Peak"),
        )

    def demand_settings_for_config(
        self,
        config: Any | None,
        circuit_id: str,
    ) -> DemandSettings:
        """Return rolling demand settings for one circuit."""
        overrides = self._coordinator.store_data.demand_settings_by_circuit.get(
            circuit_id,
            {},
        )
        default_window_minutes = (
            config.demand_window_minutes if config is not None else 15
        )
        default_limit_w = config.demand_limit_w if config is not None else None
        return DemandSettings(
            window_minutes=_positive_int_value(
                overrides.get("window_minutes"),
                default=default_window_minutes,
            ),
            demand_limit_w=_optional_positive_float_value(
                overrides.get("demand_limit_w"),
                default=default_limit_w,
            ),
        )

    def capacity_settings_for_config(self, circuit_id: str) -> CapacitySettings:
        """Return circuit capacity settings for one circuit."""
        overrides = self._coordinator.store_data.capacity_settings_by_circuit.get(
            circuit_id,
            {},
        )
        return CapacitySettings(
            breaker_amps=_optional_positive_float_value(
                overrides.get("breaker_amps"),
                default=None,
            ),
            warning_ratio=_positive_float_value(
                overrides.get("warning_ratio"),
                default=DEFAULT_CAPACITY_WARNING_RATIO,
            ),
        )

    def standby_settings_for_config(
        self,
        config: Any | None,
        circuit_id: str,
    ) -> StandbySettings:
        """Return Always On and standby settings for one circuit."""
        overrides = self._coordinator.store_data.standby_settings_by_circuit.get(
            circuit_id,
            {},
        )
        default_window_hours = (
            config.standby_window_hours if config is not None else 48
        )
        default_threshold_w = config.standby_threshold_w if config is not None else 8.0
        default_alert_w = config.always_on_alert_w if config is not None else None
        default_min_samples = config.standby_min_samples if config is not None else 24
        return StandbySettings(
            window_hours=_positive_int_value(
                overrides.get("window_hours"),
                default=default_window_hours,
            ),
            standby_threshold_w=_positive_float_value(
                overrides.get("standby_threshold_w"),
                default=default_threshold_w,
            ),
            always_on_alert_w=_optional_positive_float_value(
                overrides.get("always_on_alert_w"),
                default=default_alert_w,
            ),
            min_samples=_positive_int_value(
                overrides.get("min_samples"),
                default=default_min_samples,
            ),
        )

    def utility_comparison_settings_for_circuit(
        self,
        circuit_id: str,
    ) -> UtilityComparisonSettings:
        """Return utility-vs-measured kWh comparison settings."""
        overrides = (
            self._coordinator.store_data.utility_comparison_settings_by_circuit.get(
                circuit_id,
                {},
            )
        )
        return UtilityComparisonSettings(
            utility_energy_entity=str(overrides.get("utility_energy_entity") or ""),
            utility_statistic_id=str(overrides.get("utility_statistic_id") or ""),
            utility_source_type=str(overrides.get("utility_source_type") or "auto"),
            utility_statistic_period=_utility_statistic_period_value(
                overrides.get("utility_statistic_period")
            ),
            measured_energy_entities=_entity_id_tuple_value(
                overrides.get("measured_energy_entities"),
                default=(),
            ),
            tolerance_percent=_nonnegative_float_value(
                overrides.get("tolerance_percent"),
                default=DEFAULT_UTILITY_COMPARISON_TOLERANCE_PERCENT,
            ),
        )

    def refresh_settings_recommendation_state(self, now: Any) -> None:
        """Refresh Home Assistant state payloads for visible recommendations."""
        coordinator = self._coordinator
        by_circuit: dict[str, list[dict[str, Any]]] = {}
        pending_count_by_circuit: dict[str, int] = {}
        for recommendation in sorted(
            self.visible_settings_recommendations(now),
            key=lambda item: (
                item.circuit_name,
                item.status is not RecommendationStatus.PENDING,
                item.group,
                item.setting_label,
                item.recommendation_id,
            ),
        ):
            by_circuit.setdefault(recommendation.circuit_id, []).append(
                recommendation_to_dict(recommendation),
            )
            if recommendation.status is RecommendationStatus.PENDING:
                pending_count_by_circuit[recommendation.circuit_id] = (
                    pending_count_by_circuit.get(recommendation.circuit_id, 0) + 1
                )
        coordinator.state.settings_recommendations_by_circuit = by_circuit
        coordinator.state.settings_recommendation_count_by_circuit = {
            circuit_id: count
            for circuit_id, count in pending_count_by_circuit.items()
            if count > 0
        }
        if not pending_count_by_circuit:
            coordinator.notification_controller.set_settings_recommendation_notification_episode_key(
                ()
            )

    def visible_settings_recommendations(
        self,
        now: Any,
    ) -> list[Any]:
        """Return unexpired recommendations shown in entity/panel payloads."""
        recommendations = self._coordinator.store_data.settings_recommendations
        return [
            recommendation
            for recommendation in recommendations.values()
            if recommendation.status
            in {RecommendationStatus.PENDING, RecommendationStatus.APPLIED}
            and recommendation.expires_at > now
        ]

    def pending_settings_recommendations(
        self,
        now: Any,
    ) -> list[Any]:
        """Return unexpired pending recommendations."""
        recommendations = self._coordinator.store_data.settings_recommendations
        return [
            recommendation
            for recommendation in recommendations.values()
            if recommendation.status is RecommendationStatus.PENDING
            and recommendation.expires_at > now
        ]

    async def async_set_energy_usage_settings(
        self,
        circuit_id: str,
        window_days: Any = None,
        daily_spike_ratio: Any = None,
    ) -> None:
        """Persist daily energy usage spike settings for one circuit."""
        coordinator = self._coordinator
        config = coordinator.circuit_registry.config_for_circuit(circuit_id)
        current = self.energy_usage_settings_for_config(config, circuit_id)
        settings = {
            "window_days": _positive_int_value(
                window_days,
                default=current.window_days,
            ),
            "daily_spike_ratio": _positive_float_value(
                daily_spike_ratio,
                default=current.daily_spike_ratio,
            ),
        }
        await self._async_save_circuit_settings(
            circuit_id,
            coordinator.store_data.energy_usage_settings_by_circuit,
            settings,
        )

    async def async_set_energy_goal_settings(
        self,
        circuit_id: str,
        daily_goal_kwh: Any = None,
        goal_alert_ratio: Any = None,
    ) -> None:
        """Persist daily energy goal settings for one circuit."""
        coordinator = self._coordinator
        config = coordinator.circuit_registry.config_for_circuit(circuit_id)
        current = self.energy_goal_settings_for_config(config, circuit_id)
        settings: dict[str, Any] = {
            "goal_alert_ratio": _positive_float_value(
                goal_alert_ratio,
                default=current.goal_alert_ratio,
            ),
        }
        if daily_goal_kwh is None:
            if current.daily_goal_kwh is not None:
                settings["daily_goal_kwh"] = current.daily_goal_kwh
        else:
            goal_kwh = _optional_positive_float_value(
                daily_goal_kwh,
                default=None,
            )
            settings["daily_goal_kwh"] = goal_kwh if goal_kwh is not None else 0.0
        coordinator.store_data.energy_goal_settings_by_circuit[circuit_id] = settings
        coordinator.store_persistence.mark_dirty()
        now = coordinator._now_fn()
        goal_result = coordinator._energy_goal_processor.refresh_state(
            circuit_id,
            config,
            coordinator.context_builder.build(now),
        )
        await coordinator._apply_feature_result(goal_result)
        coordinator._refresh_ux_state_for_circuit(circuit_id, now)
        coordinator.async_set_updated_data(coordinator.state)
        await coordinator.store_persistence.async_save_if_dirty(now)

    async def async_set_activity_alert_settings(
        self,
        circuit_id: str,
        max_active_minutes: Any = None,
        max_idle_minutes: Any = None,
    ) -> None:
        """Persist user-configured activity alert settings for one circuit."""
        coordinator = self._coordinator
        current = self.activity_alert_settings_for_config(None, circuit_id)
        max_minutes = _optional_positive_float_value(
            max_active_minutes,
            default=current.max_active_minutes,
        )
        max_idle = _optional_positive_float_value(
            max_idle_minutes,
            default=current.max_idle_minutes,
        )
        settings: dict[str, Any] = {}
        if max_minutes is not None:
            settings["max_active_minutes"] = max_minutes
        if max_idle is not None:
            settings["max_idle_minutes"] = max_idle
        await self._async_save_circuit_settings(
            circuit_id,
            coordinator.store_data.activity_alert_settings_by_circuit,
            settings,
        )

    async def async_set_demand_settings(
        self,
        circuit_id: str,
        window_minutes: Any = None,
        demand_limit_w: Any = None,
    ) -> None:
        """Persist rolling demand settings for one circuit."""
        coordinator = self._coordinator
        config = coordinator.circuit_registry.config_for_circuit(circuit_id)
        current = self.demand_settings_for_config(config, circuit_id)
        settings: dict[str, Any] = {
            "window_minutes": _positive_int_value(
                window_minutes,
                default=current.window_minutes,
            ),
        }
        limit_w = _optional_positive_float_value(
            demand_limit_w,
            default=current.demand_limit_w,
        )
        if limit_w is not None:
            settings["demand_limit_w"] = limit_w
        await self._async_save_circuit_settings(
            circuit_id,
            coordinator.store_data.demand_settings_by_circuit,
            settings,
        )

    async def async_set_capacity_settings(
        self,
        circuit_id: str,
        breaker_amps: Any = None,
        warning_ratio: Any = None,
    ) -> None:
        """Persist circuit capacity settings for one circuit."""
        coordinator = self._coordinator
        current = self.capacity_settings_for_config(circuit_id)
        settings: dict[str, Any] = {
            "warning_ratio": _positive_float_value(
                warning_ratio,
                default=current.warning_ratio,
            ),
        }
        capacity_amps = _optional_positive_float_value(
            breaker_amps,
            default=current.breaker_amps,
        )
        if capacity_amps is not None:
            settings["breaker_amps"] = capacity_amps
        await self._async_save_circuit_settings(
            circuit_id,
            coordinator.store_data.capacity_settings_by_circuit,
            settings,
        )

    async def async_set_standby_settings(
        self,
        circuit_id: str,
        window_hours: Any = None,
        standby_threshold_w: Any = None,
        always_on_alert_w: Any = None,
    ) -> None:
        """Persist Always On and standby settings for one circuit."""
        coordinator = self._coordinator
        config = coordinator.circuit_registry.config_for_circuit(circuit_id)
        current = self.standby_settings_for_config(config, circuit_id)
        settings: dict[str, Any] = {
            "window_hours": _positive_int_value(
                window_hours,
                default=current.window_hours,
            ),
            "standby_threshold_w": _positive_float_value(
                standby_threshold_w,
                default=current.standby_threshold_w,
            ),
        }
        alert_w = _optional_positive_float_value(
            always_on_alert_w,
            default=current.always_on_alert_w,
        )
        if alert_w is not None:
            settings["always_on_alert_w"] = alert_w
        await self._async_save_circuit_settings(
            circuit_id,
            coordinator.store_data.standby_settings_by_circuit,
            settings,
        )

    async def async_set_billing_cycle_settings(
        self,
        circuit_id: str,
        cycle_start_day: Any = None,
        budget_kwh: Any = None,
        budget_alert_ratio: Any = None,
    ) -> None:
        """Persist billing-cycle usage forecast settings for one circuit."""
        coordinator = self._coordinator
        config = coordinator.circuit_registry.config_for_circuit(circuit_id)
        current = self.billing_cycle_settings_for_config(config, circuit_id)
        settings: dict[str, Any] = {
            "cycle_start_day": _positive_int_value(
                cycle_start_day,
                default=current.cycle_start_day,
            ),
            "budget_alert_ratio": _positive_float_value(
                budget_alert_ratio,
                default=current.budget_alert_ratio,
            ),
        }
        budget = _optional_positive_float_value(
            budget_kwh,
            default=current.budget_kwh,
        )
        if budget is not None:
            settings["budget_kwh"] = budget
        await self._async_save_circuit_settings(
            circuit_id,
            coordinator.store_data.billing_settings_by_circuit,
            settings,
        )

    async def async_set_cost_settings(
        self,
        circuit_id: str,
        cycle_start_day: Any = None,
        default_rate_per_kwh: Any = None,
        tou_rate_per_kwh: Any = None,
        tou_start: Any = None,
        tou_end: Any = None,
        tou_weekdays: Any = None,
        tou_name: Any = None,
    ) -> None:
        """Persist cost and Time-of-Use settings for one circuit."""
        coordinator = self._coordinator
        config = coordinator.circuit_registry.config_for_circuit(circuit_id)
        current = self.cost_settings_for_config(config, circuit_id)
        settings: dict[str, Any] = {
            "cycle_start_day": _positive_int_value(
                cycle_start_day,
                default=current.cycle_start_day,
            ),
        }
        default_rate = _optional_positive_float_value(
            default_rate_per_kwh,
            default=current.default_rate_per_kwh,
        )
        tou_rate = _optional_positive_float_value(
            tou_rate_per_kwh,
            default=current.tou_rate_per_kwh,
        )
        if default_rate is not None:
            settings["default_rate_per_kwh"] = default_rate
        if tou_rate is not None:
            settings["tou_rate_per_kwh"] = tou_rate
        settings["tou_start"] = str(tou_start or current.tou_start or "")
        settings["tou_end"] = str(tou_end or current.tou_end or "")
        weekdays = _weekday_csv_value(
            tou_weekdays,
            default=current.tou_weekdays,
        )
        if weekdays:
            settings["tou_weekdays"] = weekdays
        settings["tou_name"] = str(tou_name or current.tou_name or "Peak")
        await self._async_save_circuit_settings(
            circuit_id,
            coordinator.store_data.cost_settings_by_circuit,
            settings,
        )

    async def async_set_utility_comparison_settings(
        self,
        circuit_id: str,
        utility_energy_entity: Any = None,
        measured_energy_entities: Any = None,
        tolerance_percent: Any = None,
        utility_statistic_id: Any = None,
        utility_source_type: Any = None,
        utility_statistic_period: Any = None,
    ) -> None:
        """Persist utility-vs-measured kWh comparison settings."""
        coordinator = self._coordinator
        current = self.utility_comparison_settings_for_circuit(circuit_id)
        utility_entity = (
            current.utility_energy_entity
            if utility_energy_entity is None
            else str(utility_energy_entity).strip()
        )
        utility_statistic = (
            current.utility_statistic_id
            if utility_statistic_id is None
            else str(utility_statistic_id).strip()
        )
        source_type = (
            current.utility_source_type
            if utility_source_type is None
            else str(utility_source_type).strip()
        )
        statistic_period = (
            current.utility_statistic_period
            if utility_statistic_period is None
            else str(utility_statistic_period).strip()
        )
        measured_entities = _entity_id_tuple_value(
            measured_energy_entities,
            default=current.measured_energy_entities,
        )
        settings: dict[str, Any] = {
            "tolerance_percent": _nonnegative_float_value(
                tolerance_percent,
                default=current.tolerance_percent,
            ),
        }
        if utility_entity:
            settings["utility_energy_entity"] = utility_entity
        if utility_statistic:
            settings["utility_statistic_id"] = utility_statistic
        if source_type:
            settings["utility_source_type"] = source_type
        if statistic_period:
            settings["utility_statistic_period"] = statistic_period
        if measured_entities:
            settings["measured_energy_entities"] = list(measured_entities)
        await self._async_save_circuit_settings(
            circuit_id,
            coordinator.store_data.utility_comparison_settings_by_circuit,
            settings,
        )

    async def async_set_leg_imbalance_settings(
        self,
        circuit_id: str,
        warning_ratio: Any = None,
        minimum_total_power_w: Any = None,
    ) -> None:
        """Persist dual-phase leg imbalance thresholds for one circuit."""
        current = self._coordinator.store_data.leg_imbalance_settings_by_circuit.get(
            circuit_id,
            {},
        )
        settings = {
            "warning_ratio": _positive_float_value(
                warning_ratio,
                default=_positive_float_value(
                    current.get("warning_ratio"),
                    default=DEFAULT_LEG_IMBALANCE_WARNING_RATIO,
                ),
            ),
            "minimum_total_power_w": _nonnegative_float_value(
                minimum_total_power_w,
                default=_nonnegative_float_value(
                    current.get("minimum_total_power_w"),
                    default=DEFAULT_LEG_IMBALANCE_MIN_TOTAL_POWER_W,
                ),
            ),
        }
        await self._async_save_circuit_settings(
            circuit_id,
            self._coordinator.store_data.leg_imbalance_settings_by_circuit,
            settings,
        )

    async def async_set_metric_consistency_settings(
        self,
        circuit_id: str,
        apparent_power_tolerance_percent: Any = None,
        power_factor_tolerance: Any = None,
        minimum_apparent_power_va: Any = None,
    ) -> None:
        """Persist W/VA/PF consistency thresholds for one circuit."""
        current = (
            self._coordinator.store_data.metric_consistency_settings_by_circuit.get(
                circuit_id,
                {},
            )
        )
        settings = {
            "apparent_power_tolerance_percent": _positive_float_value(
                apparent_power_tolerance_percent,
                default=_positive_float_value(
                    current.get("apparent_power_tolerance_percent"),
                    default=DEFAULT_APPARENT_POWER_TOLERANCE_PERCENT,
                ),
            ),
            "power_factor_tolerance": _positive_float_value(
                power_factor_tolerance,
                default=_positive_float_value(
                    current.get("power_factor_tolerance"),
                    default=DEFAULT_POWER_FACTOR_TOLERANCE,
                ),
            ),
            "minimum_apparent_power_va": _nonnegative_float_value(
                minimum_apparent_power_va,
                default=_nonnegative_float_value(
                    current.get("minimum_apparent_power_va"),
                    default=DEFAULT_MIN_APPARENT_POWER_VA,
                ),
            ),
        }
        await self._async_save_circuit_settings(
            circuit_id,
            self._coordinator.store_data.metric_consistency_settings_by_circuit,
            settings,
        )

    async def async_set_mains_balance_settings(
        self,
        circuit_id: str,
        negative_tolerance_w: Any = None,
    ) -> None:
        """Persist mains-minus-monitored balance thresholds."""
        current = self._coordinator.store_data.balance_settings_by_circuit.get(
            circuit_id,
            {},
        )
        settings = {
            "negative_tolerance_w": _nonnegative_float_value(
                negative_tolerance_w,
                default=_nonnegative_float_value(
                    current.get("negative_tolerance_w"),
                    default=DEFAULT_BALANCE_NEGATIVE_TOLERANCE_W,
                ),
            ),
        }
        await self._async_save_circuit_settings(
            circuit_id,
            self._coordinator.store_data.balance_settings_by_circuit,
            settings,
        )

    async def async_set_solar_flow_settings(
        self,
        circuit_id: str,
        export_tolerance_w: Any = None,
        solar_surplus_threshold_w: Any = None,
        high_solar_surplus_threshold_w: Any = None,
        flexible_load_running_threshold_w: Any = None,
    ) -> None:
        """Persist solar flow and flexible-load thresholds."""
        current = self._coordinator.store_data.solar_flow_settings_by_circuit.get(
            circuit_id,
            {},
        )
        settings = {
            "export_tolerance_w": _nonnegative_float_value(
                export_tolerance_w,
                default=_nonnegative_float_value(
                    current.get("export_tolerance_w"),
                    default=EXPORT_TOLERANCE_W,
                ),
            ),
            "solar_surplus_threshold_w": _nonnegative_float_value(
                solar_surplus_threshold_w,
                default=_nonnegative_float_value(
                    current.get("solar_surplus_threshold_w"),
                    default=SOLAR_SURPLUS_THRESHOLD_W,
                ),
            ),
            "high_solar_surplus_threshold_w": _nonnegative_float_value(
                high_solar_surplus_threshold_w,
                default=_nonnegative_float_value(
                    current.get("high_solar_surplus_threshold_w"),
                    default=HIGH_SOLAR_SURPLUS_THRESHOLD_W,
                ),
            ),
            "flexible_load_running_threshold_w": _nonnegative_float_value(
                flexible_load_running_threshold_w,
                default=_nonnegative_float_value(
                    current.get("flexible_load_running_threshold_w"),
                    default=FLEXIBLE_LOAD_RUNNING_THRESHOLD_W,
                ),
            ),
        }
        await self._async_save_circuit_settings(
            circuit_id,
            self._coordinator.store_data.solar_flow_settings_by_circuit,
            settings,
        )

    async def _async_save_circuit_settings(
        self,
        circuit_id: str,
        settings_by_circuit: MutableMapping[str, Any],
        settings: Any,
    ) -> None:
        coordinator = self._coordinator
        settings_by_circuit[circuit_id] = settings
        coordinator.store_persistence.mark_dirty()
        now = coordinator._now_fn()
        coordinator._refresh_ux_state_for_circuit(circuit_id, now)
        coordinator.async_set_updated_data(coordinator.state)
        await coordinator.store_persistence.async_save_if_dirty(now)

    async def async_apply_setting_recommendation(
        self,
        recommendation_id: str,
    ) -> None:
        """Apply one pending setting recommendation to advanced settings."""
        coordinator = self._coordinator
        recommendation = coordinator.store_data.settings_recommendations.get(
            recommendation_id,
        )
        if (
            recommendation is None
            or recommendation.status is not RecommendationStatus.PENDING
        ):
            return

        for setting_key, value in recommendation.apply_payload.items():
            self.set_recommendation_setting_value(
                recommendation.circuit_id,
                str(setting_key),
                value,
            )
        if any(
            key in OPERATING_DETECTION_OVERRIDE_FIELDS
            for key in recommendation.apply_payload
        ):
            self.set_recommendation_setting_value(
                recommendation.circuit_id,
                OPERATING_DETECTION_SOURCE,
                OperatingThresholdSource.LEARNED_RECOMMENDATION.value,
            )
        await coordinator.config_entry_controller.async_persist_options()

        coordinator.store_data.settings_recommendations[recommendation_id] = replace(
            recommendation,
            status=RecommendationStatus.APPLIED,
        )
        coordinator.store_persistence.mark_dirty()
        now = coordinator._now_fn()
        self.refresh_settings_recommendation_state(now)
        coordinator._refresh_ux_state_for_circuit(recommendation.circuit_id, now)
        coordinator.async_set_updated_data(coordinator.state)
        await coordinator.store_persistence.async_save_if_dirty(now)

    async def async_undo_setting_recommendation(
        self,
        recommendation_id: str,
    ) -> bool:
        """Restore the value recorded before an applied recommendation."""
        coordinator = self._coordinator
        recommendation = coordinator.store_data.settings_recommendations.get(
            recommendation_id,
        )
        if (
            recommendation is None
            or recommendation.status is not RecommendationStatus.APPLIED
        ):
            return False

        self.set_recommendation_setting_value(
            recommendation.circuit_id,
            recommendation.setting_key,
            recommendation.current_value,
        )
        await coordinator.config_entry_controller.async_persist_options()
        coordinator.store_data.settings_recommendations[recommendation_id] = replace(
            recommendation,
            status=RecommendationStatus.PENDING,
        )
        coordinator.store_persistence.mark_dirty()
        now = coordinator._now_fn()
        self.refresh_settings_recommendation_state(now)
        coordinator._refresh_ux_state_for_circuit(recommendation.circuit_id, now)
        coordinator.async_set_updated_data(coordinator.state)
        await coordinator.store_persistence.async_save_if_dirty(now)
        return True

    async def async_reset_setting_recommendation(
        self,
        recommendation_id: str,
    ) -> bool:
        """Reset a recommendation-backed setting to its built-in default."""
        coordinator = self._coordinator
        recommendation = coordinator.store_data.settings_recommendations.get(
            recommendation_id,
        )
        if recommendation is None:
            return False

        default_value = recommendation_setting_default_value(
            recommendation.setting_key,
        )
        self.set_recommendation_setting_value(
            recommendation.circuit_id,
            recommendation.setting_key,
            default_value,
        )
        await coordinator.config_entry_controller.async_persist_options()
        coordinator.store_data.settings_recommendations[recommendation_id] = replace(
            recommendation,
            status=RecommendationStatus.STALE,
        )
        coordinator.store_persistence.mark_dirty()
        now = coordinator._now_fn()
        self.refresh_settings_recommendation_state(now)
        coordinator._refresh_ux_state_for_circuit(recommendation.circuit_id, now)
        coordinator.async_set_updated_data(coordinator.state)
        await coordinator.store_persistence.async_save_if_dirty(now)
        return True

    def set_recommendation_setting_value(
        self,
        circuit_id: str,
        setting_key: str,
        value: Any,
    ) -> None:
        """Write one recommendation-backed advanced setting value."""
        coordinator = self._coordinator
        advanced_by_circuit = coordinator.options.setdefault(
            CONF_ADVANCED_SETTINGS,
            {},
        )
        if not isinstance(advanced_by_circuit, dict):
            advanced_by_circuit = dict(advanced_by_circuit)
            coordinator.options[CONF_ADVANCED_SETTINGS] = advanced_by_circuit
        current_settings = advanced_by_circuit.get(circuit_id, {})
        updated_settings = (
            dict(current_settings) if isinstance(current_settings, Mapping) else {}
        )
        self.clear_advanced_setting_value(circuit_id, setting_key)
        if value is None:
            updated_settings.pop(setting_key, None)
        else:
            updated_settings[setting_key] = value
            self.apply_advanced_settings(circuit_id, {setting_key: value})
        if updated_settings:
            advanced_by_circuit[circuit_id] = updated_settings
        else:
            advanced_by_circuit.pop(circuit_id, None)

    def replace_advanced_settings(
        self,
        circuit_id: str,
        settings: Mapping[str, Any],
    ) -> None:
        """Replace all store-backed advanced setting groups for one circuit."""
        self.clear_advanced_settings(circuit_id)
        self.apply_advanced_settings(circuit_id, settings)

    def clear_advanced_settings(self, circuit_id: str) -> None:
        """Clear all store-backed advanced setting groups for one circuit."""
        store_data = self._coordinator.store_data
        store_data.sensitivity_by_circuit.pop(circuit_id, None)
        store_data.energy_usage_settings_by_circuit.pop(circuit_id, None)
        store_data.energy_goal_settings_by_circuit.pop(circuit_id, None)
        store_data.activity_alert_settings_by_circuit.pop(circuit_id, None)
        store_data.billing_settings_by_circuit.pop(circuit_id, None)
        store_data.cost_settings_by_circuit.pop(circuit_id, None)
        store_data.demand_settings_by_circuit.pop(circuit_id, None)
        store_data.capacity_settings_by_circuit.pop(circuit_id, None)
        store_data.standby_settings_by_circuit.pop(circuit_id, None)
        store_data.leg_imbalance_settings_by_circuit.pop(circuit_id, None)
        store_data.metric_consistency_settings_by_circuit.pop(circuit_id, None)
        store_data.balance_settings_by_circuit.pop(circuit_id, None)
        store_data.solar_flow_settings_by_circuit.pop(circuit_id, None)
        store_data.operating_detection_settings_by_circuit.pop(circuit_id, None)

    def apply_advanced_settings(
        self,
        circuit_id: str,
        settings: Mapping[str, Any],
    ) -> None:
        """Apply advanced setting values to their store-backed setting groups."""
        if not settings:
            return

        store_data = self._coordinator.store_data
        sensitivity = settings.get("preset")
        if sensitivity:
            store_data.sensitivity_by_circuit[circuit_id] = normalize_sensitivity(
                str(sensitivity)
            )

        _replace_if_present(
            store_data.energy_usage_settings_by_circuit,
            circuit_id,
            settings,
            ("window_days", "daily_spike_ratio"),
        )
        _replace_if_present(
            store_data.energy_goal_settings_by_circuit,
            circuit_id,
            settings,
            ("daily_goal_kwh", "goal_alert_ratio"),
        )
        _replace_if_present(
            store_data.activity_alert_settings_by_circuit,
            circuit_id,
            settings,
            ("max_active_minutes", "max_idle_minutes"),
        )
        _replace_if_present(
            store_data.billing_settings_by_circuit,
            circuit_id,
            settings,
            (
                "cycle_start_day",
                "budget_kwh",
                "budget_alert_ratio",
                "min_elapsed_days",
            ),
        )
        _replace_if_present(
            store_data.cost_settings_by_circuit,
            circuit_id,
            settings,
            (
                "cycle_start_day",
                "default_rate_per_kwh",
                "tou_rate_per_kwh",
                "tou_start",
                "tou_end",
                "tou_weekdays",
                "tou_name",
            ),
        )
        _replace_if_present(
            store_data.demand_settings_by_circuit,
            circuit_id,
            settings,
            ("window_minutes", "demand_limit_w"),
        )
        _replace_if_present(
            store_data.capacity_settings_by_circuit,
            circuit_id,
            settings,
            ("breaker_amps", "warning_ratio"),
        )
        _replace_if_present(
            store_data.standby_settings_by_circuit,
            circuit_id,
            settings,
            (
                "window_hours",
                "standby_threshold_w",
                "always_on_alert_w",
                "min_samples",
            ),
        )
        _replace_if_present_as(
            store_data.leg_imbalance_settings_by_circuit,
            circuit_id,
            settings,
            {
                "leg_imbalance_warning_ratio": "warning_ratio",
                "leg_imbalance_min_total_power_w": "minimum_total_power_w",
            },
        )
        _replace_if_present(
            store_data.metric_consistency_settings_by_circuit,
            circuit_id,
            settings,
            (
                "apparent_power_tolerance_percent",
                "power_factor_tolerance",
                "minimum_apparent_power_va",
            ),
        )
        _replace_if_present_as(
            store_data.balance_settings_by_circuit,
            circuit_id,
            settings,
            {"balance_negative_tolerance_w": "negative_tolerance_w"},
        )
        _replace_if_present_as(
            store_data.solar_flow_settings_by_circuit,
            circuit_id,
            settings,
            {
                "solar_export_tolerance_w": "export_tolerance_w",
                "solar_surplus_threshold_w": "solar_surplus_threshold_w",
                "high_solar_surplus_threshold_w": (
                    "high_solar_surplus_threshold_w"
                ),
                "flexible_load_running_threshold_w": (
                    "flexible_load_running_threshold_w"
                ),
            },
        )
        _replace_if_present(
            store_data.operating_detection_settings_by_circuit,
            circuit_id,
            settings,
            (*OPERATING_DETECTION_OVERRIDE_FIELDS, OPERATING_DETECTION_SOURCE),
        )

    def advanced_settings_for_circuit(self, circuit_id: str) -> dict[str, Any]:
        """Return merged advanced settings for one circuit."""
        coordinator = self._coordinator
        settings: dict[str, Any] = {}
        for source in (
            coordinator.entry_data.get(CONF_ADVANCED_SETTINGS, {}),
            coordinator.options.get(CONF_ADVANCED_SETTINGS, {}),
        ):
            if not isinstance(source, Mapping):
                continue
            raw_settings = source.get(circuit_id, {})
            if isinstance(raw_settings, Mapping):
                settings.update(dict(raw_settings))

        store_data = coordinator.store_data
        settings.update(
            store_data.energy_usage_settings_by_circuit.get(circuit_id, {}),
        )
        settings.update(
            store_data.activity_alert_settings_by_circuit.get(circuit_id, {}),
        )
        settings.update(store_data.demand_settings_by_circuit.get(circuit_id, {}))
        settings.update(store_data.capacity_settings_by_circuit.get(circuit_id, {}))
        settings.update(store_data.standby_settings_by_circuit.get(circuit_id, {}))
        settings.update(
            store_data.metric_consistency_settings_by_circuit.get(
                circuit_id,
                {},
            ),
        )

        leg_imbalance = store_data.leg_imbalance_settings_by_circuit.get(
            circuit_id,
            {},
        )
        if "warning_ratio" in leg_imbalance:
            settings["leg_imbalance_warning_ratio"] = leg_imbalance["warning_ratio"]
        if "minimum_total_power_w" in leg_imbalance:
            settings["leg_imbalance_min_total_power_w"] = leg_imbalance[
                "minimum_total_power_w"
            ]

        balance = store_data.balance_settings_by_circuit.get(circuit_id, {})
        if "negative_tolerance_w" in balance:
            settings["balance_negative_tolerance_w"] = balance[
                "negative_tolerance_w"
            ]

        solar_flow = store_data.solar_flow_settings_by_circuit.get(
            circuit_id,
            {},
        )
        if "export_tolerance_w" in solar_flow:
            settings["solar_export_tolerance_w"] = solar_flow["export_tolerance_w"]
        for key in (
            "solar_surplus_threshold_w",
            "high_solar_surplus_threshold_w",
            "flexible_load_running_threshold_w",
        ):
            if key in solar_flow:
                settings[key] = solar_flow[key]

        settings.update(
            store_data.operating_detection_settings_by_circuit.get(
                circuit_id,
                {},
            )
        )

        return settings

    def clear_advanced_setting_value(self, circuit_id: str, setting_key: str) -> None:
        """Clear one recommendation-backed value from stored setting groups."""
        store_data = self._coordinator.store_data
        if setting_key == "preset":
            store_data.sensitivity_by_circuit.pop(circuit_id, None)
            return
        _remove_setting_key(
            store_data.energy_usage_settings_by_circuit,
            circuit_id,
            setting_key,
        )
        _remove_setting_key(
            store_data.energy_goal_settings_by_circuit,
            circuit_id,
            setting_key,
        )
        _remove_setting_key(
            store_data.activity_alert_settings_by_circuit,
            circuit_id,
            setting_key,
        )
        _remove_setting_key(
            store_data.billing_settings_by_circuit,
            circuit_id,
            setting_key,
        )
        _remove_setting_key(
            store_data.cost_settings_by_circuit,
            circuit_id,
            setting_key,
        )
        _remove_setting_key(
            store_data.demand_settings_by_circuit,
            circuit_id,
            setting_key,
        )
        _remove_setting_key(
            store_data.capacity_settings_by_circuit,
            circuit_id,
            setting_key,
        )
        _remove_setting_key(
            store_data.standby_settings_by_circuit,
            circuit_id,
            "min_samples" if setting_key == "standby_min_samples" else setting_key,
        )
        _remove_setting_key(
            store_data.leg_imbalance_settings_by_circuit,
            circuit_id,
            {
                "leg_imbalance_warning_ratio": "warning_ratio",
                "leg_imbalance_min_total_power_w": "minimum_total_power_w",
            }.get(setting_key, setting_key),
        )
        _remove_setting_key(
            store_data.metric_consistency_settings_by_circuit,
            circuit_id,
            setting_key,
        )
        _remove_setting_key(
            store_data.balance_settings_by_circuit,
            circuit_id,
            {
                "balance_negative_tolerance_w": "negative_tolerance_w",
            }.get(setting_key, setting_key),
        )
        _remove_setting_key(
            store_data.solar_flow_settings_by_circuit,
            circuit_id,
            {
                "solar_export_tolerance_w": "export_tolerance_w",
            }.get(setting_key, setting_key),
        )
        _remove_setting_key(
            store_data.operating_detection_settings_by_circuit,
            circuit_id,
            setting_key,
        )

    async def async_deny_setting_recommendation(self, recommendation_id: str) -> None:
        """Record a denial for one pending setting recommendation."""
        await self.async_record_setting_recommendation_decision(
            recommendation_id,
            RecommendationStatus.DENIED,
        )

    async def async_dismiss_setting_recommendation(
        self,
        recommendation_id: str,
    ) -> None:
        """Record a dismissal for one pending setting recommendation."""
        await self.async_record_setting_recommendation_decision(
            recommendation_id,
            RecommendationStatus.DISMISSED,
        )

    async def async_record_setting_recommendation_decision(
        self,
        recommendation_id: str,
        status: RecommendationStatus,
    ) -> None:
        """Record a terminal decision for one pending setting recommendation."""
        coordinator = self._coordinator
        recommendation = coordinator.store_data.settings_recommendations.get(
            recommendation_id,
        )
        if (
            recommendation is None
            or recommendation.status is not RecommendationStatus.PENDING
        ):
            return

        now = coordinator._now_fn()
        coordinator.store_data.settings_recommendations[recommendation_id] = replace(
            recommendation,
            status=status,
        )
        coordinator.store_data.settings_recommendation_decisions[
            recommendation.unique_key
        ] = RecommendationDecision(
            unique_key=recommendation.unique_key,
            status=status,
            decided_at=now,
            denied_value=recommendation.suggested_value,
            evidence_fingerprint=recommendation_evidence_fingerprint(
                recommendation,
            ),
        )
        coordinator.store_persistence.mark_dirty()
        self.refresh_settings_recommendation_state(now)
        coordinator.async_set_updated_data(coordinator.state)
        await coordinator.store_persistence.async_save_if_dirty(now)


def _merged_entry_settings_map(
    entry_data: Mapping[str, Any],
    options: Mapping[str, Any],
    key: str,
) -> dict[str, dict[str, Any]]:
    settings: dict[str, dict[str, Any]] = {}
    for source in (entry_data.get(key, {}), options.get(key, {})):
        if not isinstance(source, Mapping):
            continue
        for circuit_id, value in source.items():
            if isinstance(value, Mapping):
                settings[str(circuit_id)] = dict(value)
    return settings


def _recommendation_materially_matches(
    existing: SettingRecommendation,
    candidate: SettingRecommendation,
) -> bool:
    return _recommendation_material_key(existing) == _recommendation_material_key(
        candidate,
    )


def _recommendation_material_key(
    recommendation: SettingRecommendation,
) -> tuple[Any, ...]:
    return (
        recommendation.recommendation_id,
        recommendation.unique_key,
        recommendation.circuit_id,
        recommendation.circuit_name,
        recommendation.setting_key,
        recommendation.setting_label,
        recommendation.current_value,
        recommendation.suggested_value,
        recommendation.unit,
        recommendation.feature,
        recommendation.group,
        round(recommendation.confidence, 3),
        recommendation.reason,
        tuple(sorted(dict(recommendation.apply_payload).items())),
        material_recommendation_evidence_key(
            recommendation.feature,
            recommendation.evidence,
        ),
        recommendation.advisor_version,
    )


def material_recommendation_evidence_key(
    feature: str,
    evidence: Mapping[str, Any],
) -> tuple[tuple[str, Any], ...]:
    ignored_keys: set[str] = set()
    if feature == "capacity_warning_ratio":
        ignored_keys.add("observed_samples")
    return tuple(
        sorted(
            (key, value)
            for key, value in dict(evidence).items()
            if key not in ignored_keys
        )
    )


def _remove_setting_key(
    settings_by_circuit: MutableMapping[str, dict[str, Any]],
    circuit_id: str,
    setting_key: str,
) -> None:
    settings = settings_by_circuit.get(circuit_id)
    if not isinstance(settings, dict):
        return
    settings.pop(setting_key, None)
    if not settings:
        settings_by_circuit.pop(circuit_id, None)


def _replace_if_present(
    target: MutableMapping[str, dict[str, Any]],
    circuit_id: str,
    source: Mapping[str, Any],
    keys: tuple[str, ...],
) -> None:
    values = {key: source[key] for key in keys if key in source}
    if values:
        target[circuit_id] = values


def _replace_if_present_as(
    target: MutableMapping[str, dict[str, Any]],
    circuit_id: str,
    source: Mapping[str, Any],
    key_map: Mapping[str, str],
) -> None:
    values = {
        output_key: source[input_key]
        for input_key, output_key in key_map.items()
        if input_key in source
    }
    if values:
        target[circuit_id] = values


def _positive_int_value(value: Any, *, default: int) -> int:
    try:
        parsed = int(value)
    except (TypeError, ValueError):
        return default
    return parsed if parsed > 0 else default


def _positive_float_value(value: Any, *, default: float) -> float:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return default
    return parsed if parsed > 0.0 else default


def _numeric_items(
    raw_items: Any,
    *,
    keys: tuple[str, ...] = (),
) -> list[float]:
    if raw_items is None:
        return []
    try:
        items = list(raw_items)
    except TypeError:
        items = [raw_items]

    values: list[float] = []
    for item in items:
        if keys and isinstance(item, Mapping):
            for key in keys:
                if key in item:
                    _append_float(values, item.get(key))
                    break
            continue
        _append_float(values, item)
    return values


def _append_float(values: list[float], raw_value: Any) -> None:
    try:
        value = float(raw_value)
    except (TypeError, ValueError):
        return
    values.append(value)


def _sum_optional_values(*raw_values: Any) -> float | None:
    values = _numeric_items(raw_values)
    if not values:
        return None
    return sum(abs(value) for value in values)


def _optional_float_value(value: Any) -> float | None:
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _absolute_float_value(value: Any) -> float:
    parsed = _optional_float_value(value)
    return abs(parsed) if parsed is not None else 0.0


def _optional_positive_float_value(
    value: Any,
    *,
    default: float | None,
) -> float | None:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return default
    return parsed if parsed > 0.0 else default


def _entity_id_tuple_value(
    value: Any,
    *,
    default: tuple[str, ...] = (),
) -> tuple[str, ...]:
    if value is None:
        return default
    if isinstance(value, str):
        raw_items: Any = value.replace("\n", ",").split(",")
    elif isinstance(value, (list, tuple, set)):
        raw_items = value
    else:
        return default
    return tuple(str(item).strip() for item in raw_items if str(item).strip())


def _weekday_tuple_value(
    value: Any,
    *,
    default: tuple[int, ...] = (),
) -> tuple[int, ...]:
    if value is None:
        return default
    if isinstance(value, str):
        raw_items: Any = value.split(",")
    elif isinstance(value, (list, tuple, set)):
        raw_items = value
    else:
        return default
    weekdays: list[int] = []
    for item in raw_items:
        try:
            weekday = int(str(item).strip())
        except (TypeError, ValueError):
            continue
        if 0 <= weekday <= 6 and weekday not in weekdays:
            weekdays.append(weekday)
    return tuple(weekdays) if weekdays else default


def _weekday_csv_value(value: Any, *, default: tuple[int, ...] = ()) -> str:
    return ",".join(str(day) for day in _weekday_tuple_value(value, default=default))


def _alert_policy_for_sensitivity(sensitivity: str) -> ConservativeAlertPolicy:
    policy_name = alert_policy_name_for_sensitivity(sensitivity)
    if policy_name == "high":
        return ConservativeAlertPolicy(
            min_repeated=3,
            min_total_score=2.4,
            min_average_score=1.2,
        )
    if policy_name == "low":
        return ConservativeAlertPolicy(
            min_repeated=4,
            min_total_score=6.0,
            min_average_score=1.8,
        )
    return ConservativeAlertPolicy()


def _utility_statistic_period_value(value: Any) -> str:
    normalized = str(value or DEFAULT_UTILITY_STATISTIC_PERIOD).strip().lower()
    if normalized not in {"hour", "day", "month"}:
        return DEFAULT_UTILITY_STATISTIC_PERIOD
    return normalized


def _nonnegative_float_value(value: Any, *, default: float) -> float:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        return default
    return parsed if parsed >= 0.0 else default
