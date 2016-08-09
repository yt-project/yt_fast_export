"""
openPMD-specific fields



"""

# -----------------------------------------------------------------------------
# Copyright (c) 2013, yt Development Team.
# Copyright (c) 2015, Daniel Grassinger (HZDR)
# Copyright (c) 2016, Fabian Koller (HZDR)
#
# Distributed under the terms of the Modified BSD License.
#
# The full license is in the file COPYING.txt, distributed with this software.
# -----------------------------------------------------------------------------

import numpy as np

from yt.fields.field_info_container import FieldInfoContainer
from yt.fields.magnetic_field import setup_magnetic_field_aliases
from yt.frontends.open_pmd.misc import parse_unit_dimension
from yt.units.yt_array import YTQuantity
from yt.utilities.logger import ytLogger as mylog
from yt.utilities.physical_constants import speed_of_light


def setup_poynting_vector(self):
    def _get_poyn(axis):
        def poynting(field, data):
            u = 79577.4715459  # = 1/magnetic permeability
            if axis in "x":
                return u * (data["E_y"] * data["magnetic_field_z"] - data["E_z"] * data["magnetic_field_y"])
            elif axis in "y":
                return u * (data["E_z"] * data["magnetic_field_x"] - data["E_x"] * data["magnetic_field_z"])
            elif axis in "z":
                return u * (data["E_x"] * data["magnetic_field_y"] - data["E_y"] * data["magnetic_field_x"])

        return poynting

    for ax in "xyz":
        self.add_field(("openPMD", "poynting_vector_%s" % ax),
                       function=_get_poyn(ax),
                       units="T*V/m")


def setup_kinetic_energy(self, ptype):
    def _kin_en(field, data):
        p2 = (data[ptype, "particle_momentum_x"] ** 2 +
              data[ptype, "particle_momentum_y"] ** 2 +
              data[ptype, "particle_momentum_z"] ** 2)
        mass = data[ptype, "particle_mass"] * data[ptype, "particle_weighting"]
        return speed_of_light * np.sqrt(p2 + mass ** 2 * speed_of_light ** 2) - mass * speed_of_light ** 2

    self.add_field((ptype, "particle_kinetic_energy"),
                   function=_kin_en,
                   units="kg*m**2/s**2",
                   particle_type=True)


def setup_velocity(self, ptype):
    def _get_vel(axis):
        def velocity(field, data):
            c = speed_of_light
            momentum = data[ptype, "particle_momentum_{}".format(axis)]
            mass = data[ptype, "particle_mass"]
            weighting = data[ptype, "particle_weighting"]
            return momentum / np.sqrt(
                (mass * weighting) ** 2 +
                (momentum ** 2) / (c ** 2)
            )

        return velocity

    for ax in "xyz":
        self.add_field((ptype, "particle_velocity_%s" % ax),
                       function=_get_vel(ax),
                       units="m/s",
                       particle_type=True)


def setup_absolute_positions(self, ptype):
    def _abs_pos(axis):
        def ap(field, data):
            return np.add(data[ptype, "particle_positionCoarse_{}".format(axis)],
                          data[ptype, "particle_positionOffset_{}".format(axis)])

        return ap

    for ax in "xyz":
        self.add_field((ptype, "particle_position_%s" % ax),
                       function=_abs_pos(ax),
                       units="m",
                       particle_type=True)


class OpenPMDFieldInfo(FieldInfoContainer):
    """Specifies which fields from the dataset yt should know about.

    ``self.known_other_fields`` and ``self.known_particle_fields`` must be populated.
    Entries for both of these lists must be tuples of the form
        ("name", ("units", ["fields", "to", "alias"], "display_name"))
    These fields will be represented and handled in yt in the way you define them here.
    The fields defined in both ``self.known_other_fields`` and ``self.known_particle_fields`` will only be added
    to a dataset (with units, aliases, etc), if they match any entry in the ``OpenPMDHierarchy``'s ``self.field_list``.

    Notes
    -----

    Contrary to many other frontends, we dynamically obtain the known fields from the simulation output.
    The openPMD markup is extremely flexible - names, dimensions and the number of individual datasets
    can (and very likely will) vary.

    openPMD states that names of records and their components are only allowed to contain the
        characters a-Z,
        the numbers 0-9
        and the underscore _
        (equivalently, the regex \w).
    Since yt widely uses the underscore in field names, openPMD's underscores (_) are replaced by hyphen (-).

    The constructor of the super-class is called after the fields have been dynamically parsed, so they are known when
    needed during the call of ``setup_fluid_aliases`` .

    Derived fields will automatically be set up, if names and units of your known on-disk (or manually derived)
    fields match the ones in [1].

    References
    ----------
    .. http://yt-project.org/docs/dev/analyzing/fields.html
    .. http://yt-project.org/docs/dev/developing/creating_frontend.html#data-meaning-structures
    .. https://github.com/openPMD/openPMD-standard/blob/latest/STANDARD.md
    .. [1] http://yt-project.org/docs/dev/reference/field_list.html#universal-fields
    """
    _mag_fields = []

    def __init__(self, ds, field_list):
        f = ds._handle
        bp = ds.base_path
        mp = ds.meshes_path
        pp = ds.particles_path
        fields = f[bp + mp]

        for fname in fields.keys():
            field = fields.get(fname)
            if "dataset" in str(field).split(" ")[1]:
                # We have a dataset, don't consider axes. This appears to be a vector field of single dimensionality
                ytname = str("_".join([fname.replace("_", "-")]))
                if ds._nonstandard:
                    parsed = ""
                else:
                    parsed = parse_unit_dimension(np.asarray(field.attrs["unitDimension"], dtype="int"))
                unit = str(YTQuantity(1, parsed).units)
                aliases = []
                # Save a list of magnetic fields for aliasing later on
                # We can not reasonably infer field type/unit by name in openPMD
                if unit in "T" or "kg/(A*s**2)" in unit:
                    self._mag_fields.append(ytname)
                self.known_other_fields += ((ytname, (unit, aliases, None)),)
            else:
                if ds._nonstandard:
                    axes = "xyz"  # naively assume all fields in non-standard files are 3D
                else:
                    axes = field.attrs["axisLabels"]
                for axis in axes:
                    ytname = str("_".join([fname.replace("_", "-"), axis]))
                    if ds._nonstandard:
                        parsed = ""
                    else:
                        parsed = parse_unit_dimension(np.asarray(field.attrs["unitDimension"], dtype="int"))
                    unit = str(YTQuantity(1, parsed).units)
                    aliases = []
                    # Save a list of magnetic fields for aliasing later on
                    # We can not reasonably infer field type by name in openPMD
                    if unit in "T" or "kg/(A*s**2)" in unit:
                        self._mag_fields.append(ytname)
                    self.known_other_fields += ((ytname, (unit, aliases, None)),)
        for i in self.known_other_fields:
            mylog.debug("oPMD - fields - known_other_fields - {}".format(i))

        particle_fields = ()
        particles = f[bp + pp]
        for species in particles.keys():
            for attrib in particles.get(species).keys():
                if "weighting" in attrib:
                    particle_fields += (("particle_weighting", ("", [], None)),)
                    continue
                try:
                    if ds._nonstandard:
                        if "globalCellIdx" in attrib or "position" in attrib:
                            parsed = "m"  # Required for spatial selection of particles
                        else:
                            parsed = ""
                    else:
                        parsed = parse_unit_dimension(
                            np.asarray(particles.get(species).get(attrib).attrs["unitDimension"], dtype="int"))
                    unit = str(YTQuantity(1, parsed).units)
                    name = ["particle", attrib]
                    ytattrib = attrib
                    if ytattrib in "position":
                        # Symbolically rename position to preserve yt's interpretation of the pfield
                        # particle_position is later derived in setup_absolute_positions in the way yt expects it
                        ytattrib = "positionCoarse"
                    for axis in particles.get(species).get(attrib).keys():
                        aliases = []
                        if axis in "rxyz":
                            name = ["particle", ytattrib, axis]
                        ytname = str("_".join([name.replace("_", "-")]))
                        if ds._nonstandard and "globalCellIdx" in ytname:
                            aliases.append(ytname.replace("globalCellIdx", "positionOffset"))
                        particle_fields += ((ytname, (unit, aliases, None)),)
                except:
                    mylog.info("{}_{} does not seem to have unitDimension".format(species, attrib))
        self.known_particle_fields = particle_fields
        for i in self.known_particle_fields:
            mylog.debug("oPMD - fields - known_particle_fields - {}".format(i))
        super(OpenPMDFieldInfo, self).__init__(ds, field_list)

    def setup_fluid_fields(self):
        """Defines which derived mesh fields to create.

        If a field can not be calculated, it will simply be skipped.
        """
        # Set up aliases first so the setup for poynting can use them
        if len(self._mag_fields) > 0:
            setup_magnetic_field_aliases(self, "openPMD", self._mag_fields)
            setup_poynting_vector(self)

    def setup_particle_fields(self, ptype):
        """Defines which derived particle fields to create.

        This will be called for every entry in `OpenPMDDataset``'s ``self.particle_types``.
        If a field can not be calculated, it will simply be skipped.
        """
        setup_absolute_positions(self, ptype)
        setup_kinetic_energy(self, ptype)
        setup_velocity(self, ptype)
        super(OpenPMDFieldInfo, self).setup_particle_fields(ptype)
