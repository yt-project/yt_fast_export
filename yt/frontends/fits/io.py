"""
FITS-specific IO functions
"""

#-----------------------------------------------------------------------------
# Copyright (c) 2013, yt Development Team.
#
# Distributed under the terms of the Modified BSD License.
#
# The full license is in the file COPYING.txt, distributed with this software.
#-----------------------------------------------------------------------------

import numpy as np

from yt.utilities.io_handler import \
    BaseIOHandler
from yt.utilities.logger import ytLogger as mylog

class IOHandlerFITS(BaseIOHandler):
    _particle_reader = False
    _dataset_type = "fits"

    def __init__(self, pf):
        super(IOHandlerFITS, self).__init__(pf)
        self.pf = pf
        self._handle = pf._handle
        self.folded = False
        if self.pf.folded_axis is not None:
            self.folded = True

    def _read_particles(self, fields_to_read, type, args, grid_list,
            count_list, conv_factors):
        pass

    def _read_particle_coords(self, chunks, ptf):
        pdata = self.pf._handle[self.pf.first_image].data
        assert(len(ptf) == 1)
        ptype = ptf.keys()[0]
        x = np.asarray(pdata.field("X"), dtype="=f8")
        y = np.asarray(pdata.field("Y"), dtype="=f8")
        z = np.ones(x.shape)
        yield ptype, (x,y,z)

    def _read_particle_fields(self, chunks, ptf, selector):
        pdata = self.pf._handle[self.pf.first_image].data
        assert(len(ptf) == 1)
        ptype = ptf.keys()[0]
        field_list = ptf[ptype]
        x = np.asarray(pdata.field("X"), dtype="=f8")
        y = np.asarray(pdata.field("Y"), dtype="=f8")
        z = np.ones(x.shape)
        mask = selector.select_points(x, y, z)
        if mask is None: return
        for field in field_list:
            data = pdata.field(field.split("_")[-1].upper())
            yield (ptype, field), data[mask]

    def _read_fluid_selection(self, chunks, selector, fields, size):
        chunks = list(chunks)
        if any((ftype != "fits" for ftype, fname in fields)):
            raise NotImplementedError
        rv = {}
        dt = "float64"
        for field in fields:
            rv[field] = np.empty(size, dtype=dt)
        ng = sum(len(c.objs) for c in chunks)
        mylog.debug("Reading %s cells of %s fields in %s grids",
                    size, [f2 for f1, f2 in fields], ng)
        dx = self.pf.domain_width/self.pf.domain_dimensions
        for field in fields:
            ftype, fname = field
            tmp_fname = fname
            if fname in self.pf.line_database:
                fname = self.pf.field_list[0][1]
            f = self.pf.index._file_map[fname]
            ds = f[self.pf.index._ext_map[fname]]
            bzero, bscale = self.pf.index._scale_map[fname]
            fname = tmp_fname
            ind = 0
            for chunk in chunks:
                for g in chunk.objs:
                    start = ((g.LeftEdge-self.pf.domain_left_edge)/dx).astype("int")
                    end = ((g.RightEdge-self.pf.domain_left_edge)/dx).astype("int")
                    if self.folded:
                        my_off = \
                            self.pf.line_database.get(fname,
                                                      self.pf.folded_width/2)\
                            - self.pf.folded_width/2
                        my_off = max(my_off, 0)
                        my_off = min(my_off,
                                     self.pf._unfolded_domain_dimensions[
                                         self.pf.folded_axis]-1)

                        start[-1] = start[-1] + my_off
                        end[-1] = end[-1] + my_off
                        mylog.debug("Reading from " + str(start) + str(end))
                    if self.pf.dimensionality == 2:
                        nx, ny = g.ActiveDimensions[:2]
                        nz = 1
                        data = np.zeros((nx,ny,nz))
                        data[:,:,0] = ds.data[start[1]:end[1],start[0]:end[0]].transpose()
                    elif self.pf.naxis == 4:
                        idx = self.pf.index._axis_map[fname]
                        data = ds.data[idx,start[2]:end[2],start[1]:end[1],start[0]:end[0]].transpose()
                    else:
                        data = ds.data[start[2]:end[2],start[1]:end[1],start[0]:end[0]].transpose()
                    if fname in self.pf.nan_mask:
                        data[np.isnan(data)] = self.pf.nan_mask[fname]
                    elif "all" in self.pf.nan_mask:
                        data[np.isnan(data)] = self.pf.nan_mask["all"]
                    data = bzero + bscale*data
                    ind += g.select(selector, data.astype("float64"), rv[field], ind)
        return rv
