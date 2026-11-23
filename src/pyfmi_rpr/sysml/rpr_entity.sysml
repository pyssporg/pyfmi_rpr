// RPR entity-state FMU definition owned by pyfmi_rpr.
//
// Roles: `fmu_meta` is build metadata and names the artifact to package; the
// runtime signals are `in port entityState`, the state this entity publishes,
// supplied by the model and encoded onto the wire, and `out port peerState`,
// the state received from the wire and exposed to the simulation. There is
// deliberately no `parameters` port: the RPR wire contract excludes parameter
// interfaces, and identity, type, marking and force are payload fields, not
// configuration.
//
// The dialect has no struct/record type and a typed attribute on a port
// collapses to one Real, so the port is flat: one attribute per proto leaf,
// pinned by pysos_rpr.schema_paths. `bytes` fields are not representable and
// are omitted: spatial.dead_reckoning.parameters (the FMI codec defaults them
// to empty).

package RprEntity {
    private import ScalarValues::*;
    private import PysspCore::*;

    attribute def RprEntityMetadata :> FmuMetadata {
        attribute source : String = "RprEntity.fmu";
        attribute implementation : String = "CoSimulation";
    }

    port def EntityState {
        attribute entity_identifier_site           : Integer;
        attribute entity_identifier_application    : Integer;
        attribute entity_identifier_entity         : Integer;
        attribute entity_type_kind                 : Integer;
        attribute entity_type_domain               : Integer;
        attribute entity_type_country              : Integer;
        attribute entity_type_category             : Integer;
        attribute entity_type_subcategory          : Integer;
        attribute entity_type_specific             : Integer;
        attribute entity_type_extra                : Integer;
        attribute marking_character_set            : Integer;
        attribute marking_characters               : String;
        attribute force                            : Integer = 0;
        // Position is geocentric ECEF, metres.
        attribute spatial_world_location_x         : Real;
        attribute spatial_world_location_y         : Real;
        attribute spatial_world_location_z         : Real;
        // Orientation is Euler (psi, theta, phi) = (yaw, pitch, roll), radians.
        attribute spatial_orientation_psi          : Real;
        attribute spatial_orientation_theta        : Real;
        attribute spatial_orientation_phi          : Real;
        // Linear velocity is body frame, m/s.
        attribute spatial_velocity_x               : Real;
        attribute spatial_velocity_y               : Real;
        attribute spatial_velocity_z               : Real;
        // Linear acceleration is body frame, m/s².
        attribute spatial_acceleration_x           : Real;
        attribute spatial_acceleration_y           : Real;
        attribute spatial_acceleration_z           : Real;
        // Angular velocity is body frame, rad/s.
        attribute spatial_angular_velocity_x       : Real;
        attribute spatial_angular_velocity_y       : Real;
        attribute spatial_angular_velocity_z       : Real;
        // Dead-reckoning algorithm enum 0..9. `parameters` is omitted: `bytes`
        // is not representable here and the codec defaults it empty.
        attribute spatial_dead_reckoning_algorithm : Integer = 0;
        attribute spatial_is_frozen                : Boolean;
    }

    // Build metadata: the RPR contract this port mirrors. A typed container,
    // so it stays model-owned data: not a flat parameter, not an FMI variable.
    // A consumer compares `version` with the implementation's proto package
    // before trusting the flat leaves; the leaf set is pinned by
    // pysos_rpr.schema_paths.
    attribute def RprContract {
        attribute version : String = "rpr.v2";
    }

    part def RprEntity :> FmuModel {
        attribute fmu_meta : RprEntityMetadata;
        attribute rpr_contract : RprContract;
        // State this entity publishes; supplied by the model and encoded onto
        // the wire.
        in port entityState : EntityState;
        // Peer state received from the wire and exposed to the simulation.
        out port peerState : EntityState;
    }
}
