# Discovery walk: wellsfargo.com mortgage rates (manual, via Claude in Chrome)

One walk, one profile, rates as of 9/22/2026 10:15 AM ET. This is ground truth for the AOP and the offline
fixture, not a Jev run.

| # | Screen | Observed | Design implication |
|---|---|---|---|
| 1 | Home | Two matches for "Check rates": link "Check all rates" and button "Check rates opens dropdown" | Target ambiguity; AOP rule names the button |
| 2 | Rates card | Native `<select>` defaulting to "Mortgage rates"; "Go" is `type=submit` | SELECT may be a no-op; `type=submit` is not a safe irreversibility signal (D9) |
| 3 | Rates page | Defaults: Austin, TX / $400,000 / $80,000; link "Change rate inputs" | Acceptance must check our inputs |
| 4 | Dialog "Change rate inputs" | City, State autocomplete: "Charlotte" → AR, IA, MI, NC, TN; Done disabled until a suggestion is clicked; suggestions render asynchronously | TYPE_TEXT then CLICK suggestion; settle before observing |
| 4b | same | Home price $300,000 auto-recalculated down payment $80,000 → $60,000 | Expected derived change; AOP rule so `unexpected_change` does not fire |
| 4c | same | Close (X) button has no accessible name | Observer fallback `(unlabeled button)` |
| 5 | Dialog "Select a County" | Cabarrus / Mecklenburg / Union as `div role=radio` with `aria-checked`, hidden input; clicking a radio re-rendered the dialog (earlier references went stale) | Readback via `aria-checked`; re-observe after every action; StaleTarget = re-decide |
| 6 | Rates reload | Still Austin at +3 s, Charlotte / $300,000 / $60,000 by ~+7 s | Acceptance polling (10 s); WAIT not counted as no-progress |
| 7 | Product list | "30-Year Fixed Rate" last, next to "30-Year Fixed-Rate VA", below the fold | Exact-name rule; include off-screen elements |
| 8 | Details dialog | 12 label/value pairs in divs with hashed CSS-module classes; heading text "30-Year Fixed Rate, undefined"; a hidden privacy `role=dialog` also in the DOM | Selectors would rot per deploy (D6); visibility-checked dialog detection |
| — | Whole flow | 0 open shadow roots, 1 iframe | Shadow DOM covered by the fixture, not this site |

Captured fields (that run): Credit score 760; Property type Single family; Occupancy Primary residence;
Location Charlotte, NC; Escrow account Required; Down Payment 20%; Loan amount $240,000; Loan term 30 years;
Discount points 1.000 ($2,400 due at closing); APR 7.215%; Interest rate 7.000%; Monthly payment $1,597.
