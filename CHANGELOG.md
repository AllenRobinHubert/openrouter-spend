# Changelog

## 0.4.1

- Defer state access until the first callback so registration passes the isolated capability probe.
- Declare the existing llm_execution middleware and OpenRouter key requirement for catalog validation.
- Add minimum Hermes compatibility metadata and explicit data-access disclosures.

## 0.4.0

- Public source package with MIT license, installation and accounting documentation.
- Selected-key table spend now reconciles with the provider total; unknown/different-key and manual costs are shown separately.
- Unassigned API spend remains inside the existing Other row in both profile and model tables.
- This-chat confirmed cost appears in the closed status bar and popup.
- Monthly comparison label and USD/INR amounts are configurable.
- Older desktop SDKs fail gracefully when focused-chat state is unavailable.
- Added regression tests for unknown-key image charges, manual Other entries, configurable comparisons and the desktop UI.
