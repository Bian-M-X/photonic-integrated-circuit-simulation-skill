# Native Lumerical field previews

These files are unmodified previews of actual local FDTD monitor exports,
generated on 2026-10-29 with the retained optical-device campaign. They are
user-generated scientific outputs, not redistributed Ansys binaries, license
files or vendor example datasets.

Both use the declared `2d-scalar-index-surrogate` model. The selected input is
the first physical port. Coordinates are native nonuniform monitor samples;
the visualized quantity is `10 log10(sum(abs(E)^2)/max)`, with an independent
global maximum for each image and a display range from −40 to 0 dB. It is a
relative electric-field-squared quantity, not absolute Poynting flux.

- `coupler_field.png`: 1548.3870968 nm, left-upper input. The field run reached
  the automatic stopping condition; the last recorded residual was about
  `4.98e-8`.
- `ring_field.png`: 1573.7704918 nm, left-lower input. This was the largest Drop
  output among five coarse spectral samples, not an established resonance.
  The run reached its 3 ps time-window cap with residual about `5.29e-4`; it
  does not establish steady-state convergence, linewidth, Q or group delay.

The additional field monitor was placed in a model copy. Each retained
source-column S matrix matched the corresponding earlier native result with
maximum complex difference zero. Original native models were unchanged.

Source-data procedures and the complete device scope are described in the
[device test report](../../research/lumerical-device-workflow-2026-10-29.md).
Raw native projects and field arrays remain outside the public source tree.

The published files are copied byte-for-byte from those inspected previews;
their SHA-256 values are recorded below for reproducible image identity.

| File | Bytes | SHA-256 |
|---|---:|---|
| `coupler_field.png` | 413,964 | `58bf69cc716ae900ea39b59861c1e9e583385e4659e3526f79d167ccd9e70cb0` |
| `ring_field.png` | 464,941 | `ace2a0009e2acb76b08de9fad804abbaa527400e60686be7e25b61b020ec00e3` |
