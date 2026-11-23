// A container system with one RPR entity component.
// `System` is the exportable SSP boundary (`:> SspModel`), not an FmuModel, so
// it composes `RprEntity` and never becomes an FMU itself.
package RprSystem {
    private import PysspCore::*;
    private import RprEntity::*;

    part def System :> SspModel {
        part entity : RprEntity;
    }
}
