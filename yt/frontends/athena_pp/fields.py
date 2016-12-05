"""
Athena++-specific fields



"""

#-----------------------------------------------------------------------------
# Copyright (c) 2013, yt Development Team.
#
# Distributed under the terms of the Modified BSD License.
#
# The full license is in the file COPYING.txt, distributed with this software.
#-----------------------------------------------------------------------------

from yt.fields.field_info_container import \
    FieldInfoContainer
from yt.utilities.physical_constants import \
    kboltz, mh

b_units = "code_magnetic"
pres_units = "code_mass/(code_length*code_time**2)"
rho_units = "code_mass / code_length**3"
vel_units = "code_length / code_time"

def velocity_field(j):
    def _velocity(field, data):
        return data["athena_pp", "mom%d" % j]/data["athena_pp","dens"]
    return _velocity

class AthenaPPFieldInfo(FieldInfoContainer):
    known_other_fields = (
        ("rho", (rho_units, ["density"], None)),
        ("dens", (rho_units, ["density"], None)),
        ("B1", (b_units, [], None)),
        ("B2", (b_units, [], None)),
        ("B3", (b_units, [], None)),
    )

    def setup_fluid_fields(self):
        from yt.fields.magnetic_field import \
            setup_magnetic_field_aliases
        unit_system = self.ds.unit_system
        # Add velocity fields
        vel_prefix = "velocity"
        for i, comp in enumerate(self.ds.coordinates.axis_order):
            vel_field = ("athena_pp", "vel%d" % (i+1))
            mom_field = ("athena_pp", "mom%d" % (i+1))
            if vel_field in self.field_list:
                self.add_output_field(vel_field, sampling_type="cell", units="code_length/code_time")
                self.alias(("gas","%s_%s" % (vel_prefix, comp)), vel_field,
                           units=unit_system["velocity"])
            elif mom_field in self.field_list:
                self.add_output_field(mom_field, sampling_type="cell",
                                      units="code_mass/code_time/code_length**2")
                self.add_field(("gas","%s_%s" % (vel_prefix, comp)), sampling_type="cell",
                               function=velocity_field(i+1), units=unit_system["velocity"])
        # Figure out thermal energy field
        if ("athena_pp","pgas") in self.field_list:
            self.add_output_field(("athena_pp","pgas"), sampling_type="cell",
                                  units=pres_units)
            self.alias(("gas","pressure"),("athena_pp","pgas"),
                       units=unit_system["pressure"])
            def _thermal_energy(field, data):
                return data["athena++","pgas"] / \
                       (data.ds.gamma-1.)/data["athena++","rho"]
        elif ("athena_pp","Etot") in self.field_list:
            self.add_output_field(("athena++","Etot"), sampling_type="cell",
                                  units=pres_units)
            def _thermal_energy(field, data):
                eint = data["athena_pp", "Etot"] - data["gas","kinetic_energy"]
                if ("athena_pp", "B1") in self.field_list:
                    eint -= data["gas","magnetic_energy"]
                return eint/data["athena_pp","dens"]
        self.add_field(("gas","thermal_energy"), sampling_type="cell",
                       function=_thermal_energy,
                       units=unit_system["specific_energy"])
        # Add temperature field
        def _temperature(field, data):
            if data.has_field_parameter("mu"):
                mu = data.get_field_parameter("mu")
            else:
                mu = 0.6
            return mu*mh*data["gas","pressure"]/data["gas","density"]/kboltz
        self.add_field(("gas","temperature"), sampling_type="cell", function=_temperature,
                       units=unit_system["temperature"])

        setup_magnetic_field_aliases(self, "athena_pp", ["B%d" % ax for ax in (1,2,3)])
