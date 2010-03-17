"""
Simple transfer function editor

Author: Matthew Turk <matthewturk@gmail.com>
Affiliation: KIPAC/SLAC/Stanford
Homepage: http://yt.enzotools.org/
License:
  Copyright (C) 2009 Matthew Turk.  All Rights Reserved.

  This file is part of yt.

  yt is free software; you can redistribute it and/or modify
  it under the terms of the GNU General Public License as published by
  the Free Software Foundation; either version 3 of the License, or
  (at your option) any later version.

  This program is distributed in the hope that it will be useful,
  but WITHOUT ANY WARRANTY; without even the implied warranty of
  MERCHANTABILITY or FITNESS FOR A PARTICULAR PURPOSE.  See the
  GNU General Public License for more details.

  You should have received a copy of the GNU General Public License
  along with this program.  If not, see <http://www.gnu.org/licenses/>.
"""

import numpy as na
from matplotlib.cm import get_cmap
from yt.funcs import *
from yt.physical_constants import *

class TransferFunction(object):
    def __init__(self, x_bounds, nbins=256):
        self.nbins = nbins
        self.x_bounds = x_bounds
        self.x = na.linspace(x_bounds[0], x_bounds[1], nbins).astype('float64')
        self.y = na.zeros(nbins, dtype='float64')

    def add_gaussian(self, location, width, height):
        vals = height * na.exp(-(self.x - location)**2.0/width)
        self.y = na.clip(na.maximum(vals, self.y), 0.0, 1.0)

    def add_line(self, start, stop):
        x0, y0 = start
        x1, y1 = stop
        slope = (y1-y0)/(x1-x0)
        vals = na.zeros(self.x.shape, 'float64')
        vals[(self.x >= x0) & (self.x <= x1)] = \
            slope * (self.x - x0) + y0
        self.y = na.clip(na.maximum(vals, self.y), 0.0, 1.0)

    def add_step(self,start,stop,value):
        vals = na.zeros(self.x.shape, 'float64')
        vals[(self.x >= start) & (self.x <= stop)] = value
        self.y = na.clip(na.maximum(vals, self.y), 0.0, 1.0)

    def add_filtered_planck(self, wavelength, trans):
        vals = na.zeros(self.x.shape, 'float64')
        nu = clight/(wavelength*1e-8)
        nu = nu[::-1]

        for i,logT in enumerate(self.x):
            T = 10**logT
            # Black body at this nu, T
            Bnu = ((2.0 * hcgs * nu**3) / clight**2.0) / \
                    (na.exp(hcgs * nu / (kboltz * T)) - 1.0)
            # transmission
            f = Bnu * trans[::-1]
            # integrate transmission over nu
            vals[i] = na.trapz(f,nu)

        # normalize by total transmission over filter
        self.y = vals/trans.sum() #/na.trapz(trans[::-1],nu)
        #self.y = na.clip(na.maximum(vals, self.y), 0.0, 1.0)

    def plot(self, filename):
        import matplotlib;matplotlib.use("Agg");import pylab
        pylab.clf()
        pylab.plot(self.x, self.y, 'xk-')
        pylab.xlim(*self.x_bounds)
        pylab.ylim(0.0, 1.0)
        pylab.savefig(filename)

class ColorTransferFunction(object):
    def __init__(self, x_bounds, nbins=256):
        self.x_bounds = x_bounds
        self.nbins = nbins
        self.red = TransferFunction(x_bounds, nbins)
        self.green = TransferFunction(x_bounds, nbins)
        self.blue = TransferFunction(x_bounds, nbins)
        self.alpha = TransferFunction(x_bounds, nbins)
        self.funcs = (self.red, self.green, self.blue, self.alpha)
        self.light_dir = (0.3,-0.2,0.5)
        self.light_color = (0.10, 0.10, 0.10)
        self.use_light = 0

    def add_gaussian(self, location, width, height):
        for tf, v in zip(self.funcs, height):
            tf.add_gaussian(location, width, v)

    def add_step(self, start, stop, height):
        for tf, v in zip(self.funcs, height):
            tf.add_step(start, stop, v)

    def plot(self, filename):
        from matplotlib import pyplot
        from matplotlib.ticker import FuncFormatter
        pyplot.clf()
        ax = pyplot.axes()
        i_data = na.zeros((self.alpha.x.size, self.funcs[0].y.size, 3))
        i_data[:,:,0] = na.outer(na.ones(self.alpha.x.size), self.funcs[0].y)
        i_data[:,:,1] = na.outer(na.ones(self.alpha.x.size), self.funcs[1].y)
        i_data[:,:,2] = na.outer(na.ones(self.alpha.x.size), self.funcs[2].y)
        ax.imshow(i_data, origin='lower')
        ax.fill_between(na.arange(self.alpha.y.size), self.alpha.x.size * self.alpha.y, y2=self.alpha.x.size, color='white')
        ax.set_xlim(0, self.alpha.x.size)
        xticks = na.arange(na.ceil(self.alpha.x[0]), na.floor(self.alpha.x[-1]) + 1, 1) - self.alpha.x[0]
        xticks *= self.alpha.x.size / (self.alpha.x[-1] - self.alpha.x[0])
        ax.xaxis.set_ticks(xticks)
        def x_format(x, pos):
            return "%.1f" % (x * (self.alpha.x[-1] - self.alpha.x[0]) / (self.alpha.x.size) + self.alpha.x[0])
        ax.xaxis.set_major_formatter(FuncFormatter(x_format))
        yticks = na.linspace(0,1,5) * self.alpha.y.size
        ax.yaxis.set_ticks(yticks)
        def y_format(y, pos):
            return (y / self.alpha.y.size)
        ax.yaxis.set_major_formatter(FuncFormatter(y_format))
        ax.set_ylabel("Transmission")
        ax.set_xlabel("Value")
        pyplot.savefig(filename)

    def sample_colormap(self, v, w, alpha=None, colormap="gist_stern"):
        rel = (v - self.x_bounds[0])/(self.x_bounds[1] - self.x_bounds[0])
        cmap = get_cmap(colormap)
        r,g,b,a = cmap(rel)
        if alpha is None: alpha = a
        self.add_gaussian(v, w, [r,g,b,alpha])
        print "Adding gaussian at %s with width %s and colors %s" % (
                v, w, (r,g,b,alpha))

    def add_layers(self, N, w=None, mi=None, ma=None, alpha = None,
                   colormap="gist_stern"):
        dist = (self.x_bounds[1] - self.x_bounds[0])
        if mi is None: mi = self.x_bounds[0] + dist/(10.0*N)
        if ma is None: ma = self.x_bounds[1] - dist/(10.0*N)
        if w is None: w = 0.001 * (ma-mi)/N
        if alpha is None: alpha = na.logspace(-2.0, 0.0, N)
        for v, a in zip(na.mgrid[mi:ma:N*1j], alpha):
            self.sample_colormap(v, w, a, colormap=colormap)

class MultiVariateTransferFunction(object):
    def __init__(self):
        self.n_field_tables = 0
        self.tables = []
        self.field_ids = [0]*6
        self.weight_field_ids = [-1]*6
        self.field_table_ids = [0]*6

    def add_field_table(self, table, field_id, weight_field_id = -1):
        self.tables.append(table)
        self.field_ids[self.n_field_tables] = field_id
        self.weight_field_ids[self.n_field_tables] = weight_field_id
        self.n_field_tables += 1

    def link_channels(self, table_id, channels = 0):
        channels = ensure_list(channels)
        for c in channels:
            self.field_table_ids[c] = table_id

class PlanckTransferFunction(MultiVariateTransferFunction):
    def __init__(self, T_bounds, rho_bounds, nbins=256,
                 red='R', green='V', blue='B'):
        MultiVariateTransferFunction.__init__(self)
        from UBVRI import johnson_filters
        for i, f in enumerate([red, green, blue]):
            jf = johnson_filters[f]
            tf = TransferFunction(T_bounds)
            tf.add_filtered_planck(jf['wavelen'], jf['trans'])
            self.add_field_table(tf, 0, 1)
            self.link_channels(i, i) # 0 => 0, 1 => 1, 2 => 2

        dr = (rho_bounds[1]-rho_bounds[0])/5

        tf = TransferFunction(rho_bounds)
        tf.add_line( (rho_bounds[0], 0.1), (rho_bounds[1], 0.1) )
        self.add_field_table(tf, 1)
        self.link_channels(3, 3)

        tf = TransferFunction(rho_bounds)
        tf.add_line( (rho_bounds[0], 0.1), (rho_bounds[1], 0.1) )
        self.add_field_table(tf, 1)
        self.link_channels(4, 4)

        tf = TransferFunction(rho_bounds)
        tf.add_line( (rho_bounds[0], 0.1), (rho_bounds[1], 0.1) )
        self.add_field_table(tf, 1)
        self.link_channels(5, 5)

        self._normalize()

    def _normalize(self):
        fmax  = na.array([f.y for f in self.tables[:3]])
        normal = fmax.max(axis=0)
        for f in self.tables[:3]:
            f.y = f.y/normal

if __name__ == "__main__":
    tf = ColorTransferFunction((-20, -5))
    tf.add_gaussian(-16.0, 0.4, [0.2, 0.3, 0.1])
    tf.add_gaussian(-14.0, 0.8, [0.4, 0.1, 0.2])
    tf.add_gaussian(-10.0, 1.0, [0.0, 0.0, 1.0])
    tf.plot("tf.png")
