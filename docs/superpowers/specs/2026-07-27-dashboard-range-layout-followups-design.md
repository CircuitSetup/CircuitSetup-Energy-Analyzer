# Dashboard Range And Layout Follow-ups

## Scope

Update the generated Home dashboard so that:

- **Now** always selects today as a single-day range.
- A single-day appliance tile whose health is **Learning** shows the remaining learning days, for example `Health: Learning · 4 of 7 days left`.
- Multi-day ranges hide the live House power flow section, including its colored flow bar and labels.
- The Appliances card is placed directly below All appliance power.

The Mains total power and amps and All appliance power charts remain visible for multi-day ranges.

## Data Contract

The backend learning-progress payload will carry the configured minimum learning days for each appliance profile. The Health Summary entity will expose completed and required learning days as attributes. The dashboard frontend will only calculate the remaining count from those two bounded values; it will not assume a seven-day profile or infer days from a percentage.

## Frontend Behavior

The date-range **Now** action will discard the selected range duration and preset type, then publish today's bounded start and end timestamps.

Appliance tiles will append the remaining-days text only when:

- exactly one day is selected;
- the health state is Learning; and
- valid completed and required day attributes are available.

The Home energy summary will omit its House power flow section when the selected range contains more than one calendar day. Its totals and averages remain visible.

The generated card order will be:

1. Mains total power and amps
2. All appliance power
3. Home energy summary
4. Appliances
5. Energy and costs

This places Appliances in the right column below All appliance power. Energy and costs keeps its existing multi-day-only visibility.

## Error Handling

Missing or invalid learning-day attributes fall back to the existing `Health: Learning` text. Remaining days are clamped between zero and the required count.

## Verification

Focused tests will cover:

- **Now** changing a multi-day selection to today;
- Learning remaining-days text on single-day tiles and its absence for multi-day tiles;
- the House power flow section hidden only for multi-day ranges;
- generated Home card order; and
- the frontend module cache-buster update.

The normal PR verification and Home Assistant contract suite will run before publication.
