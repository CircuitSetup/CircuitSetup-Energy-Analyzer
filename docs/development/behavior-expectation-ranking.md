# Behavior Expectation Ranking

Appliance Detail returns at most three semantically distinct expectations.
The ranking is deliberately bounded so a repeated symptom cannot crowd out a
more useful finding.

The order is:

1. blocking setup or source-data problems;
2. electrical and capacity concerns;
3. repeated behavior findings;
4. NILM validation or model conflicts;
5. energy and runtime watches;
6. context-explained behavior; and
7. learning or informational states.

Findings are deduplicated into data-quality, electrical, capacity, NILM,
runtime, energy, and context groups. Only the highest-ranked finding from a
group is shown. Maintenance returns one neutral maintenance expectation and
suppresses appliance-problem wording.

## Needs Attention

The Setup Health panel includes a compact Needs Attention list with three
categories:

- Fix Setup or Data
- Review Appliance Behavior
- Validate NILM

Normal and context-explained appliances are omitted. Each item uses the stable
direct-circuit or NILM appliance key and links to the corresponding Appliance
Detail route. Rebuilding the payload from current state removes resolved or
stale findings without storing one Home Assistant entity per item.
