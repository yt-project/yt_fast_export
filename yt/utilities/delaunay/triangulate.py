import warnings
# 2.3 compatibility
try:
    set
except NameError:
    import sets
    set = sets.Set

import numpy as np

from ._delaunay import delaunay
from interpolate import LinearInterpolator, NNInterpolator

__all__ = ['Triangulation', 'DuplicatePointWarning']


class DuplicatePointWarning(RuntimeWarning):
    """Duplicate points were passed in to the triangulation routine.
    """


class Triangulation(object):
    """A Delaunay triangulation of points in a plane.

    Triangulation(x, y)
    x, y -- the coordinates of the points as 1-D arrays of floats

    Let us make the following definitions:
        npoints = number of points input
        nedges = number of edges in the triangulation
        ntriangles = number of triangles in the triangulation

        point_id = an integer identifying a particular point (specifically, an
            index into x and y), range(0, npoints)
        edge_id = an integer identifying a particular edge, range(0, nedges)
        triangle_id = an integer identifying a particular triangle
            range(0, ntriangles)

    Attributes: (all should be treated as read-only to maintain consistency)
      x, y -- the coordinates of the points as 1-D arrays of floats.

      circumcenters -- (ntriangles, 2) array of floats giving the (x,y)
        coordinates of the circumcenters of each triangle (indexed by a
        triangle_id).

      edge_db -- (nedges, 2) array of point_id's giving the points forming
        each edge in no particular order; indexed by an edge_id.

      triangle_nodes -- (ntriangles, 3) array of point_id's giving the points
        forming each triangle in counter-clockwise order; indexed by a
        triangle_id.

      triangle_neighbors -- (ntriangles, 3) array of triangle_id's giving the
        neighboring triangle; indexed by a triangle_id.

        The value can also be -1 meaning that that edge is on the convex hull of
        the points and there is no neighbor on that edge. The values are ordered
        such that triangle_neighbors[tri, i] corresponds with the edge
        *opposite* triangle_nodes[tri, i]. As such, these neighbors are also in
        counter-clockwise order.

      hull -- list of point_id's giving the nodes which form the convex hull
        of the point set. This list is sorted in counter-clockwise order.
    """
    def __init__(self, x, y):
        self.x = np.asarray(x, dtype=np.float64)
        self.y = np.asarray(y, dtype=np.float64)

        if self.x.shape != self.y.shape or len(self.x.shape) != 1:
            raise ValueError("x,y must be equal-length 1-D arrays")

        self.old_shape = self.x.shape
        j_unique = self._collapse_duplicate_points()

        if j_unique.shape != self.x.shape:
            warnings.warn(
                "Input data contains duplicate x,y points; some values are ignored.",
                DuplicatePointWarning,
            )
            self.j_unique = j_unique
            self.x = self.x[self.j_unique]
            self.y = self.y[self.j_unique]
        else:
            self.j_unique = None


        self.circumcenters, self.edge_db, self.triangle_nodes, \
            self.triangle_neighbors = delaunay(self.x, self.y)

        self.hull = self._compute_convex_hull()

    def _collapse_duplicate_points(self):
        """Generate index array that picks out unique x,y points.

        This appears to be required by the underlying delaunay triangulation
        code.
        """
        # Find the indices of the unique entries
        j_sorted = np.lexsort(keys=(self.x, self.y))
        mask_unique = np.hstack([
            True, 
            (np.diff(self.x[j_sorted]) != 0) | (np.diff(self.y[j_sorted]) != 0),
        ])
        return j_sorted[mask_unique]

    def _compute_convex_hull(self):
        """Extract the convex hull from the triangulation information.

        The output will be a list of point_id's in counter-clockwise order
        forming the convex hull of the data set.
        """
        border = (self.triangle_neighbors == -1)

        edges = {}
        edges.update(dict(zip(self.triangle_nodes[border[:,0]][:,1],
                              self.triangle_nodes[border[:,0]][:,2])))
        edges.update(dict(zip(self.triangle_nodes[border[:,1]][:,2],
                              self.triangle_nodes[border[:,1]][:,0])))
        edges.update(dict(zip(self.triangle_nodes[border[:,2]][:,0],
                              self.triangle_nodes[border[:,2]][:,1])))

        # Take an arbitrary starting point and its subsequent node
        hull = list(edges.popitem())
        while edges:
            hull.append(edges.pop(hull[-1]))

        # hull[-1] == hull[0], so remove hull[-1]
        hull.pop()

        return hull

    def linear_interpolator(self, z, default_value=np.nan):
        """Get an object which can interpolate within the convex hull by
        assigning a plane to each triangle.

        z -- an array of floats giving the known function values at each point
          in the triangulation.
        """
        z = np.asarray(z, dtype=np.float64)
        if z.shape != self.old_shape:
            raise ValueError("z must be the same shape as x and y")
        if self.j_unique is not None:
            z = z[self.j_unique]

        return LinearInterpolator(self, z, default_value)

    def nn_interpolator(self, z, default_value=np.nan):
        """Get an object which can interpolate within the convex hull by
        the natural neighbors method.

        z -- an array of floats giving the known function values at each point
          in the triangulation.
        """
        z = np.asarray(z, dtype=np.float64)
        if z.shape != self.old_shape:
            raise ValueError("z must be the same shape as x and y")
        if self.j_unique is not None:
            z = z[self.j_unique]

        return NNInterpolator(self, z, default_value)

    def prep_extrapolator(self, z, bbox=None):
        if bbox is None:
            bbox = (self.x[0], self.x[0], self.y[0], self.y[0])
        minx, maxx, miny, maxy = np.asarray(bbox, np.float64)
        minx = min(minx, np.minimum.reduce(self.x))
        miny = min(miny, np.minimum.reduce(self.y))
        maxx = max(maxx, np.maximum.reduce(self.x))
        maxy = max(maxy, np.maximum.reduce(self.y))
        M = max((maxx-minx)/2, (maxy-miny)/2)
        midx = (minx + maxx)/2.0
        midy = (miny + maxy)/2.0

        xp, yp= np.array([[midx+3*M, midx, midx-3*M],
                          [midy, midy+3*M, midy-3*M]])
        x1 = np.hstack((self.x, xp))
        y1 = np.hstack((self.y, yp))
        newtri = self.__class__(x1, y1)

        # do a least-squares fit to a plane to make pseudo-data
        xy1 = np.ones((len(self.x), 3), np.float64)
        xy1[:,0] = self.x
        xy1[:,1] = self.y
        from numpy.dual import lstsq
        c, res, rank, s = lstsq(xy1, z)
        zp = np.hstack((z, xp*c[0] + yp*c[1] + c[2]))

        return newtri, zp

    def nn_extrapolator(self, z, bbox=None, default_value=np.nan):
        newtri, zp = self.prep_extrapolator(z, bbox)
        return newtri.nn_interpolator(zp, default_value)

    def linear_extrapolator(self, z, bbox=None, default_value=np.nan):
        newtri, zp = self.prep_extrapolator(z, bbox)
        return newtri.linear_interpolator(zp, default_value)

    def node_graph(self):
        """Return a graph of node_id's pointing to node_id's.

        The arcs of the graph correspond to the edges in the triangulation.

        {node_id: set([node_id, ...]), ...}
        """
        g = {}
        for i, j in self.edge_db:
            s = g.setdefault(i, set())
            s.add(j)
            s = g.setdefault(j, set())
            s.add(i)
        return g
