# Scientific Figure Geometry

figpact describes and adjusts the geometry of scientific figures under an author's explicit layout intent, without changing protected scientific content.

## Language

**Scene**:
The objects and spatial relationships belonging to one output version of a scientific figure.
_Avoid_: parameter list, screenshot

**Scope**:
An explicitly named range of layout ownership and verification. Scopes may share an output version or span multiple panels; a scope is neither a panel nor a filename.
_Avoid_: output file, panel, selection

**Output Version**:
A complete view of a figure, such as the main, annotated, or raw-versus-processed view, exported as a family of publication artifacts.
_Avoid_: scope, format

**Panel**:
A bounded region displaying one scientific view, image, or plot within a figure.
_Avoid_: scope

**Group**:
A declared collection of objects that shares a layout intention, such as moving together.
_Avoid_: incidental collection

**Envelope**:
A rectangle enclosing an object's displayed extent. It is not the object's visible contour.
_Avoid_: exact shape

**Relation**:
A measurable spatial relationship between declared objects, with explicit direction, reference, and units.
_Avoid_: knob, configuration key

**Gap**:
Signed separation between facing envelope edges along a specified axis; a negative gap means overlap.
_Avoid_: baseline pitch, nearest distance

**Clearance**:
The minimum distance between explicitly identified displayed shapes. Envelope clearance and local curve clearance are distinct measurements.
_Avoid_: gap without a measurement definition

**Measurement Tolerance**:
The maximum deviation an author permits for a stated layout requirement. Meeting this tolerance does not establish the physical accuracy of the measurement.
_Avoid_: calibrated accuracy

**Measurement Uncertainty**:
The established uncertainty of a measurement under its actual rendering conditions. An unknown uncertainty remains unknown; extra decimal places do not reduce it.
_Avoid_: requested tolerance, mathematical exactness

**Decorative Guide**:
Auxiliary visual geometry connecting or orienting objects, rather than a measured scientific trace. Layout freedom does not authorize moving protected scientific anchors.
_Avoid_: scientific curve, editable signal

**Layout Candidate**:
A proposed layout derived from a known baseline, with its changes, scientific invariants, diagnostics, and verification level stated.
_Avoid_: published figure, verified output

**Scientific Payload**:
Protected data, processing choices, scientific text and assignments, image content, display windows, and scale-bar meaning. Permitted layout changes do not authorize changes to this payload.
_Avoid_: editable plot data

**Scientific View Window**:
The protected selection of scientific content, such as an image crop or a chemical-shift range.
_Avoid_: layout viewport, blank headroom

**Layout Viewport**:
An explicitly authorized display region whose blank headroom may change while the scientific origin, signal scale, and content remain fixed.
_Avoid_: scientific view window, automatic rescaling

**Geometry Checked**:
A candidate checked using measurements and declared, supported geometric changes; it has not necessarily been rendered.
_Avoid_: strict verified

**Render Checked**:
A candidate measured after actual rendering and checked for the current scope. It is not full publication approval.
_Avoid_: strict verified

**Strict Verified**:
A complete publication build that passes all required output-version, scientific-invariant, and publication checks.
_Avoid_: preview passed
