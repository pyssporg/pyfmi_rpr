// A container system with one RPR entity component.
// `System` is not an FmuModel, so it composes `RprEntity` and never becomes
// an FMU itself.
package RprSystem {
    private import RprEntity::*;

    part def System {
        part entity : RprEntity;
    }
}
