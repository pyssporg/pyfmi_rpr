"""End to end over AF_UNIX: a generated FMU publishes a decodable RPR frame.

The frame crosses a real ``AF_UNIX`` datagram socket owned by the C++ transport
inside ``RprEntity.fmu``.  A Python :class:`~pysos_interop.UnixChannel` receives
the bytes, the ``pyfmi_interop`` envelope is decoded, and the RPR payload is
decoded with the neutral codec.  The FMU is regenerated here so the test fails
when a stale artifact no longer links the current transport archive.
"""

from __future__ import annotations

import os
import shutil
import uuid

import pytest

pytest.importorskip("pysos_rpr")
pytest.importorskip("pysos_interop.rpr")
fmpy = pytest.importorskip("fmpy")

from fmpy.fmi2 import FMU2Slave  # noqa: E402
from pyfmi_interop.wire import PayloadFormat  # noqa: E402
from pyfmi_interop.wire import decode as decode_wire  # noqa: E402
from pysos_interop import UnixChannel  # noqa: E402
from pysos_interop.rpr import RprOrigin, decode_frame  # noqa: E402

from pyfmi_rpr import rpr_entity  # noqa: E402

pytestmark = pytest.mark.skipif(
    any(shutil.which(program) is None for program in ("cmake", "ninja", "g++", "protoc")),
    reason="the FMU build needs cmake, ninja, g++ and protoc on PATH",
)

_ORIGIN = RprOrigin(57.7, 12.9, 100.0)
_INTEGERS = {
    "entityState.entity_identifier_site": 11,
    "entityState.entity_identifier_application": 22,
    "entityState.entity_identifier_entity": 33,
    "entityState.force": 2,
    "entityState.marking_character_set": 1,
    "entityState.spatial_dead_reckoning_algorithm": 4,
}
_REALS = {
    "entityState.spatial_world_location_x": 1000.0,
    "entityState.spatial_world_location_y": -2000.0,
    "entityState.spatial_world_location_z": 300.0,
}


@pytest.fixture(scope="module")
def entity_fmu(tmp_path_factory) -> str:
    """Regenerate the entity FMU with the transport archive currently installed."""

    from pysos_rpr.projection import generate_entity_adapter

    fmu = generate_entity_adapter(rpr_entity(), tmp_path_factory.mktemp("entity"))
    return str(fmu)


def _abstract_name(prefix: str) -> str:
    return f"@{prefix}-{os.getpid()}-{uuid.uuid4().hex}"


def _set_inputs(fmu: FMU2Slave, variables) -> None:
    by_name = {variable.name: variable for variable in variables}
    fmu.setInteger(
        [by_name[name].valueReference for name in _INTEGERS],
        list(_INTEGERS.values()),
    )
    fmu.setReal(
        [by_name[name].valueReference for name in _REALS],
        list(_REALS.values()),
    )
    fmu.setString(
        [by_name["entityState.marking_characters"].valueReference],
        ["E2E"],
    )


def test_entity_fmu_publishes_a_decodable_frame_over_unix(entity_fmu, tmp_path) -> None:
    model_description = fmpy.read_model_description(entity_fmu)
    by_name = {variable.name: variable for variable in model_description.modelVariables}
    receiver_name = _abstract_name("rpr-recv")
    sender_name = _abstract_name("rpr-send")

    fmu = FMU2Slave(
        guid=model_description.guid,
        unzipDirectory=fmpy.extract(entity_fmu, str(tmp_path / "unpacked")),
        modelIdentifier=model_description.coSimulation.modelIdentifier,
        instanceName="unix-e2e",
    )
    try:
        with UnixChannel(receiver_name, bind=True) as receiver:
            fmu.instantiate()
            fmu.setupExperiment(startTime=0.0)
            fmu.setString(
                [
                    by_name["transport"].valueReference,
                    by_name["bind_address"].valueReference,
                    by_name["peer_address"].valueReference,
                ],
                ["unix", sender_name, receiver_name],
            )
            fmu.enterInitializationMode()
            fmu.exitInitializationMode()

            _set_inputs(fmu, model_description.modelVariables)
            fmu.doStep(currentCommunicationPoint=0.0, communicationStepSize=0.1)

            raw = receiver.recv(5.0)

        frame = decode_wire(raw)
        assert PayloadFormat(frame.header.payload_format) is PayloadFormat.PROTOBUF

        decoded = decode_frame(bytes(frame.payload), origin=_ORIGIN)
        assert (
            decoded.state.key.site,
            decoded.state.key.application,
            decoded.state.key.entity,
        ) == (11, 22, 33)
        assert decoded.state.marking == "E2E"
        assert decoded.state.force_id == 2
    finally:
        fmu.terminate()
        fmu.freeInstance()
