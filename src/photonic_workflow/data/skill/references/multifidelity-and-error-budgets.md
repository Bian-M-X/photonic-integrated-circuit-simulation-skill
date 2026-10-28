# Multi-fidelity search and task error budgets

Use this when coarse candidates are nearly tied, 2D-to-3D transfer is uncertain,
or full-circuit precision is consuming excessive simulation time.

## Calibrate the ladder before trusting its ranking

Numerical mesh stability does not bound model-class error. Before expanding a
large reduced/EIM sweep, compare a small relevant vector/high-fidelity baseline
and retain the discrepancy separately from the within-model mesh difference.
Use the declared claim and available budget to choose that comparison; there is
no universal error bound inferred from one historical device.

Levels may include analytic/CMT, modal/circuit, 2D EIM, coarse 3D and converged 3D.
They are physically different models, not interchangeable numerical resolutions.
State what each can answer: vertical radiation, substrate leakage, polarization
conversion, sidewall effects and near-field coupling may be absent from low
levels. Beam envelopes require a justified slowly varying phase/envelope; EME
requires a converged modal basis and slicing. Neither is universal for strongly
scattering topology regions.

Evaluate paired low/high-fidelity anchors across the intended design region,
including edges and promising candidates. Fit bias/discrepancy only on calibration
pairs and assess it on held-out pairs. Inspect ranking inversions as well as RMS
error: an accurate average predictor can still reverse the best designs. If a
geometric change creates a mode crossing, resonance shift or topology change,
recalibrate or narrow the region. Never merge fidelities into a single-fidelity GP
as if they were repeated observations of the same function.

A useful local model is `J_H(x)=J_L(x)+delta(x)`. With limited data start with a
constant/linear correction and a trust region; a complicated discrepancy model
may overfit. Keep target-fidelity evaluations for both exploitation and checking
the correction. The largest held-out residual is an **empirical discrepancy**,
not a certified uniform error bound. GP standard deviation is not automatically
a valid error certificate either. If these are all that is available, label
screening/ranking heuristic and verify winners at target fidelity.

BoTorch's qMFKG optimizes value of information at a target fidelity with a cost
model. Consider it only after pairing evidence, sufficient data, version pinning
and backend tests. The package's `optimize suggest` is single-fidelity; it does not
implement qMFKG or automated multi-fidelity promotion.

## Resolve comparisons using an error budget

For minimized loss, suppose true losses satisfy
`|J_A - Jhat_A| <= e_A` and `|J_B - Jhat_B| <= e_B`.
Then

`J_B-J_A >= Jhat_B-Jhat_A-(e_A+e_B)`.

Thus candidate A improves on B by more than `delta` if
`Jhat_B-Jhat_A > e_A+e_B+delta`. This follows directly from the triangle inequality.
If intervals overlap, the ranking is unresolved; spend the next evaluation on
the dominant uncertainty or on a discriminating target-fidelity run. The helper
`compare_error_intervals` implements this **conditional** test and never estimates
the bounds itself. The combination is an engineering policy, not a claimed new
global-convergence theorem.

Separate mesh, domain/PML, port/mode, material, interpolation, surrogate and
process uncertainty. Without independence assumptions, sum conservative bounds;
do not automatically add them in quadrature. Fabrication variation is not solver
noise. Common errors may cancel in paired differences only when that cancellation
has been established. Relative phase errors and tiny loss differences often need
stricter checks than a scalar throughput comparison.

## Task-weighted component precision: a derived allocation rule

Uniform convergence tolerances can waste circuit-design cost. Let `e_i` bound the
error of component i's complex model, and let `L_i>0` bound the sensitivity of the
**final task metric** to that component throughout the admissible perturbation
region. A differentiable circuit mapping then gives the sufficient budget
`Σ L_i e_i <= E` by integrating its derivative along the perturbation path.
Near poles/resonances or ill-conditioned feedback, a point derivative is not a
uniform bound; establish a remainder/region bound or treat the rule as heuristic.

Assume measured local costs can be approximated by
`C_i(e_i)=a_i e_i^(-p)`, with `a_i>0`, common `p>0`. Minimizing total cost under
the linear error budget is a strictly convex problem. Its Lagrangian stationarity
condition is `p a_i e_i^(-p-1)=lambda L_i`. Substitution into the active constraint
gives

`w_i=(a_i/L_i)^(1/(p+1))`, `e_i=E w_i / Σ_j L_j w_j`.

`optimization.numerics.allocate_error_budget` implements this closed form.
Higher task sensitivity requests tighter component accuracy; expensive components
receive more error allowance where task sensitivity permits it. This combines
standard sensitivity/error propagation with a cost model; novelty is not claimed.

Fit `a_i,p` from pilots, and re-check the fit near memory/out-of-core transitions.
If p differs per component or min/max tolerances bind, solve the small constrained
allocation problem explicitly. Do not use zero measured sensitivity as permission
to discard a component. Preserve irreducible fabrication/material uncertainty
outside this numerical budget. The runtime does not compute circuit Lipschitz
bounds or automatically schedule COMSOL refinements.

## Adaptive band/corner sampling without hiding violations

Start with band endpoints, critical operating wavelengths and predicted resonances.
Add wavelengths where interpolation error, phase curvature, resonance movement or
constraint risk is highest. Track complex phase and modal identity rather than
interpolating wrapped phase. Keep a separate validation grid. A narrow resonance
can fall between every design sample, so a fixed three-wavelength optimization is
not a broadband certificate.

During robust optimization, grow an active set of violating corners/wavelengths
and periodically inspect the full declared set. Freeze the final validation set
before selecting the winner. Statistical yield requires a declared distribution,
correlations and confidence analysis; a few erosion/dilation cases are not a yield
estimate. Stop if the remaining compute budget cannot establish the intended claim.

For process perturbations, see the [axial-interaction and corner-cancellation
counterexamples](fabrication-aware-robust-design.md). Keep each geometry and its
optical response distinct until the loss/metric aggregation. An averaged wafer
image can cancel opposite process errors and does not represent the expected or
worst optical response. Sampling density, solver fidelity and process-model
accuracy are three separate budget axes.
