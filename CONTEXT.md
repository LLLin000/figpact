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

**Containment**:
An object's displayed extent staying within an explicitly identified boundary.
_Avoid_: visibility after clipping

**Overflow**:
The greatest distance an object's extent crosses the specified boundary; zero when contained.
_Avoid_: free space, boundary margin

**Boundary Margin**:
Space remaining between a contained object and its specified boundary. A margin is not existing overflow.
_Avoid_: overflow, shape-to-shape clearance

**Measurement Tolerance**:
The maximum deviation an author permits for a stated layout requirement. Meeting this tolerance does not establish the physical accuracy of the measurement.
_Avoid_: calibrated accuracy

**Measurement Uncertainty**:
The established uncertainty of a measurement under its actual rendering conditions. An unknown uncertainty remains unknown; extra decimal places do not reduce it.
_Avoid_: requested tolerance, mathematical exactness

**Measurement Mode**:
Read-only observation of objects, dimensions, and spatial relationships. Measurement does not require editable parameters and grants no authority to change a scene.
_Avoid_: editing session, publication approval

**Editing Mode**:
Proposing and saving layout changes through explicitly permitted bindings while preserving the scientific payload. Being measurable does not make an object editable.
_Avoid_: unrestricted manipulation, measurement mode

**Parameter Binding**:
An explicit connection between an allowed layout control and the objects and relationships it actually affects.
_Avoid_: measurement prerequisite, guessed control

**Binding Proof**:
Observed agreement between an allowed control change and its declared effects, with protected scientific content preserved. A rejected trial or an unchanged configuration is not evidence that a binding works.
_Avoid_: guessed effect, publication approval

**Coupled Controls**:
Layout controls that must change together to preserve a shared constraint, such as an image's aspect ratio. Failure of an isolated change does not make a valid combined change unsupported.
_Avoid_: independently editable dimensions

**Reconstruction Field**:
A protected record needed to reproduce a figure's meaning or reference state. It may be inspected but is not a layout freedom.
_Avoid_: editable parameter

**Display Lift**:
An additional permitted display displacement applied to an object. Its declared amount is not the resulting gap, clearance, or baseline pitch.
_Avoid_: measured spacing

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

**Image Placement**:
The position of protected image content within a figure's display space. Moving an image does not authorize changing its pixels or scientific view window.
_Avoid_: scientific crop, image pixel coordinates

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
