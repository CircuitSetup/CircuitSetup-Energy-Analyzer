# Settings Impact Preview

Supported advanced-setting recommendations include a dry-run comparison before
the user applies them. The comparison evaluates the current and suggested
thresholds against retained analyzer observations without changing coordinator,
storage, config-entry, or Home Assistant state.

The first supported settings cover daily energy spikes, operating on/off,
standby, circuit capacity, demand, leg imbalance, metric consistency, and NILM
confidence. Previews are limited to the newest 500 observations within 14 days,
and the response contains at most five added and five removed examples.

The panel labels the evaluated history, current and suggested counts, examples
that would change, confidence, and limitations. Missing history and unsupported
settings return explanatory preview payloads instead of failing the evidence
view. Applying, undoing, and resetting a recommendation continue through the
existing settings recommendation services; previewing never persists a value.
Operating-threshold previews use retained transition power and therefore
approximate crossings without replaying the live detector's dwell or hysteresis.
