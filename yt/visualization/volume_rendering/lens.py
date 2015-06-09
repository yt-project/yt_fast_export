"""
Lens Classes



"""

# ----------------------------------------------------------------------------
# Copyright (c) 2013, yt Development Team.
#
# Distributed under the terms of the Modified BSD License.
#
# The full license is in the file COPYING.txt, distributed with this software.
# ----------------------------------------------------------------------------

from yt.funcs import mylog
from yt.utilities.parallel_tools.parallel_analysis_interface import \
    ParallelAnalysisInterface
from yt.units.yt_array import YTArray
from yt.data_objects.image_array import ImageArray
from yt.utilities.math_utils import get_rotation_matrix
import numpy as np

from yt.utilities.lib.grid_traversal import \
    arr_fisheye_vectors


class Lens(ParallelAnalysisInterface):

    """docstring for Lens"""

    def __init__(self, ):
        super(Lens, self).__init__()
        self.viewpoint = None
        self.sub_samples = 5
        self.num_threads = 0
        self.double_check = False
        self.box_vectors = None
        self.origin = None
        self.back_center = None
        self.front_center = None
        self.sampler = None

    def set_camera(self, camera):
        self.setup_box_properties(camera)

    def new_image(self, camera):
        self.current_image = ImageArray(
            np.zeros((camera.resolution[0], camera.resolution[1],
                      4), dtype='float64', order='C'),
            info={'imtype': 'rendering'})
        return self.current_image

    def _reshape_image(self, image, camera):
        return image

    def setup_box_properties(self, camera):
        unit_vectors = camera.unit_vectors
        width = camera.width
        center = camera.focus
        self.box_vectors = YTArray([unit_vectors[0] * width[0],
                                    unit_vectors[1] * width[1],
                                    unit_vectors[2] * width[2]])
        self.origin = center - 0.5 * width.dot(YTArray(unit_vectors, ""))
        self.back_center = center - 0.5 * width[2] * unit_vectors[2]
        self.front_center = center + 0.5 * width[2] * unit_vectors[2]

        self.set_viewpoint(camera)

    def set_viewpoint(self, camera):
        """
        Set the viewpoint used for AMRKDTree traversal such that you yield
        bricks from back to front or front to back from with respect to this
        point.  Must be implemented for each Lens type.
        """
        raise NotImplementedError("Need to choose viewpoint for this class")


class PlaneParallelLens(Lens):

    """docstring for PlaneParallelLens"""

    def __init__(self, ):
        super(PlaneParallelLens, self).__init__()

    def _get_sampler_params(self, camera, render_source):
        if render_source.zbuffer is not None:
            image = render_source.zbuffer.rgba
        else:
            image = self.new_image(camera)

        sampler_params =\
            dict(vp_pos=np.concatenate([camera.inv_mat.ravel('F'),
                                        self.back_center.ravel()]),
                 vp_dir=self.box_vectors[2],  # All the same
                 center=self.back_center,
                 bounds=(-camera.width[0] / 2.0, camera.width[0] / 2.0,
                         -camera.width[1] / 2.0, camera.width[1] / 2.0),
                 x_vec=camera.unit_vectors[0],
                 y_vec=camera.unit_vectors[1],
                 width=np.array(camera.width, dtype='float64'),
                 image=image)
        return sampler_params

    def set_viewpoint(self, camera):
        # This is a hack that should be replaced by an alternate plane-parallel
        # traversal. Put the camera really far away so that the effective
        # viewpoint is infinitely far away, making for parallel rays.
        self.viewpoint = self.front_center + \
            camera.unit_vectors[2] * 1.0e6 * camera.width[2]

    def project_to_plane(self, camera, pos, res=None):
        if res is None:
            res = camera.resolution
        dx = np.dot(pos - self.origin.d, camera.unit_vectors[1])
        dy = np.dot(pos - self.origin.d, camera.unit_vectors[0])
        dz = np.dot(pos - self.front_center.d, -camera.unit_vectors[2])
        # Transpose into image coords.
        py = (res[0]*(dx/camera.width[0].d)).astype('int')
        px = (res[1]*(dy/camera.width[1].d)).astype('int')
        return px, py, dz

    def __repr__(self):
        disp = "<Lens Object>:\n\tlens_type:plane-parallel\n\tviewpoint:%s" %\
            (self.viewpoint)
        return disp


class PerspectiveLens(Lens):

    """docstring for PerspectiveLens"""

    def __init__(self):
        super(PerspectiveLens, self).__init__()
        self.expand_factor = 1.5

    def new_image(self, camera):
        self.current_image = ImageArray(
            np.zeros((camera.resolution[0]*camera.resolution[1], 1,
                      4), dtype='float64', order='C'),
            info={'imtype': 'rendering'})
        return self.current_image

    def _get_sampler_params(self, camera, render_source):
        # We should move away from pre-generation of vectors like this and into
        # the usage of on-the-fly generation in the VolumeIntegrator module
        # We might have a different width and back_center
        # dl = (self.back_center - self.front_center)
        # self.front_center += self.expand_factor*dl
        # self.back_center -= dl

        if render_source.zbuffer is not None:
            image = render_source.zbuffer.rgba
        else:
            image = self.new_image(camera)

        east_vec = camera.unit_vectors[0].reshape(3,1)
        north_vec = camera.unit_vectors[1].reshape(3,1)
        normal_vec = camera.unit_vectors[2].reshape(3,1)

        px = np.mat(np.linspace(-.5, .5, camera.resolution[0]))
        py = np.mat(np.linspace(-.5, .5, camera.resolution[1]))

        sample_x = camera.width[0] * np.array(east_vec * px).transpose()
        sample_y = camera.width[1] * np.array(north_vec * py).transpose()

        vectors = np.zeros((camera.resolution[0], camera.resolution[1], 3),
                           dtype='float64', order='C')

        sample_x = np.repeat(sample_x.reshape(camera.resolution[0],1,3), \
                             camera.resolution[1], axis=1)
        sample_y = np.repeat(sample_y.reshape(1,camera.resolution[1],3), \
                             camera.resolution[0], axis=0)

        normal_vecs = np.tile(normal_vec, camera.resolution[0] * camera.resolution[1])\
                             .reshape(camera.resolution[0], camera.resolution[1], 3)

        vectors = sample_x + sample_y + normal_vecs * camera.width[2]

        positions = np.tile(camera.position, camera.resolution[0] * camera.resolution[1])\
                           .reshape(camera.resolution[0], camera.resolution[1], 3)

        uv = np.ones(3, dtype='float64')

        image = self.new_image(camera)

        sampler_params =\
            dict(vp_pos=positions,
                 vp_dir=vectors,
                 center=self.back_center.d,
                 bounds=(0.0, 1.0, 0.0, 1.0),
                 x_vec=uv,
                 y_vec=uv,
                 width=np.zeros(3, dtype='float64'),
                 image=image
                 )

        mylog.debug(positions)
        mylog.debug(vectors)

        return sampler_params

    def set_viewpoint(self, camera):
        """
        For a PerspectiveLens, the viewpoint is the front center.
        """
        self.viewpoint = self.front_center

    def __repr__(self):
        disp = "<Lens Object>: lens_type:perspective viewpoint:%s" % \
            (self.viewpoint)
        return disp

class StereoPerspectiveLens(Lens):

    """docstring for StereoPerspectiveLens"""

    def __init__(self):
        super(StereoPerspectiveLens, self).__init__()
        self.expand_factor = 1.5

    def new_image(self, camera):
        self.current_image = ImageArray(
            np.zeros((camera.resolution[0]*camera.resolution[1], 1,
                      4), dtype='float64', order='C'),
            info={'imtype': 'rendering'})
        return self.current_image

    def _get_sampler_params(self, camera, render_source):
        # We should move away from pre-generation of vectors like this and into
        # the usage of on-the-fly generation in the VolumeIntegrator module
        # We might have a different width and back_center
        # dl = (self.back_center - self.front_center)
        # self.front_center += self.expand_factor*dl
        # self.back_center -= dl

        self.disparity = camera.width[0].d / 1000.
        single_resolution_x = np.floor(camera.resolution[0])/2

        if render_source.zbuffer is not None:
            image = render_source.zbuffer.rgba
        else:
            image = self.new_image(camera)

        east_vec = camera.unit_vectors[0].reshape(3,1)
        north_vec = camera.unit_vectors[1].reshape(3,1)
        normal_vec = camera.unit_vectors[2].reshape(3,1)

        px = np.mat(np.linspace(-.5, .5, single_resolution_x))
        py = np.mat(np.linspace(-.5, .5, camera.resolution[1]))

        sample_x = camera.width[0] * np.array(east_vec * px).transpose()
        sample_y = camera.width[1] * np.array(north_vec * py).transpose()

        vectors = np.zeros((single_resolution_x, camera.resolution[1], 3),
                           dtype='float64', order='C')

        sample_x = np.repeat(sample_x.reshape(single_resolution_x,1,3), \
                             camera.resolution[1], axis=1)
        sample_y = np.repeat(sample_y.reshape(1,camera.resolution[1],3), \
                             single_resolution_x, axis=0)

        normal_vecs = np.tile(normal_vec, single_resolution_x * camera.resolution[1])\
                             .reshape(single_resolution_x, camera.resolution[1], 3)

        vectors = sample_x + sample_y + normal_vecs * camera.width[2]

        positions = np.tile(camera.position, single_resolution_x * camera.resolution[1])\
                           .reshape(single_resolution_x, camera.resolution[1], 3)
        east_vecs = np.tile(east_vec, single_resolution_x * camera.resolution[1])\
                           .reshape(single_resolution_x, camera.resolution[1], 3)

        # The left and right are switched because VR is in LHS.
        # The shifting direction of vectors is opposite to that of positions
        vectors_left = vectors.d + east_vecs * self.disparity
        vectors_right = vectors.d + east_vecs * (-self.disparity)

        # The left and right are switched because VR is in LHS.
        positions_left = positions + east_vecs * (-self.disparity)
        positions_right = positions + east_vecs *  self.disparity

        uv = np.ones(3, dtype='float64')

        image = self.new_image(camera)
        vectors_comb = np.vstack([vectors_left, vectors_right])
        positions_comb = np.vstack([positions_left, positions_right])

        image.shape = (camera.resolution[0]*camera.resolution[1], 1, 4)
        vectors_comb.shape = (camera.resolution[0]*camera.resolution[1], 1, 3)
        positions_comb.shape = (camera.resolution[0]*camera.resolution[1], 1, 3)

        sampler_params =\
            dict(vp_pos=positions_comb,
                 vp_dir=vectors_comb,
                 center=self.back_center.d,
                 bounds=(0.0, 1.0, 0.0, 1.0),
                 x_vec=uv,
                 y_vec=uv,
                 width=np.zeros(3, dtype='float64'),
                 image=image
                 )

        mylog.debug(positions)
        mylog.debug(vectors)

        return sampler_params

    def set_viewpoint(self, camera):
        """
        For a PerspectiveLens, the viewpoint is the front center.
        """
        self.viewpoint = self.front_center

    def __repr__(self):
        disp = "<Lens Object>: lens_type:perspective viewpoint:%s" % \
            (self.viewpoint)
        return disp

class FisheyeLens(Lens):

    """docstring for FisheyeLens"""

    def __init__(self):
        super(FisheyeLens, self).__init__()
        self.fov = 180.0
        self.radius = 1.0
        self.center = None
        self.rotation_matrix = np.eye(3)

    def setup_box_properties(self, camera):
        self.radius = camera.width.max()
        super(FisheyeLens, self).setup_box_properties(camera)
        self.set_viewpoint(camera)

    def new_image(self, camera):
        self.current_image = ImageArray(
            np.zeros((camera.resolution[0]**2, 1,
                      4), dtype='float64', order='C'),
            info={'imtype': 'rendering'})
        return self.current_image

    def _get_sampler_params(self, camera, render_source):
        vp = -arr_fisheye_vectors(camera.resolution[0], self.fov)
        vp.shape = (camera.resolution[0]**2, 1, 3)
        vp = vp.dot(np.linalg.inv(self.rotation_matrix))
        vp *= self.radius
        uv = np.ones(3, dtype='float64')
        positions = np.ones((camera.resolution[0]**2, 1, 3),
                            dtype='float64') * camera.position

        if render_source.zbuffer is not None:
            image = render_source.zbuffer.rgba
        else:
            image = self.new_image(camera)

        sampler_params =\
            dict(vp_pos=positions,
                 vp_dir=vp,
                 center=self.center,
                 bounds=(0.0, 1.0, 0.0, 1.0),
                 x_vec=uv,
                 y_vec=uv,
                 width=np.zeros(3, dtype='float64'),
                 image=image
                 )

        return sampler_params

    def set_viewpoint(self, camera):
        """
        For a PerspectiveLens, the viewpoint is the front center.
        """
        self.viewpoint = camera.position

    def __repr__(self):
        disp = "<Lens Object>: lens_type:fisheye viewpoint:%s fov:%s radius:" %\
            (self.viewpoint, self.fov, self.radius)
        return disp

    def project_to_plane(self, camera, pos, res=None):
        if res is None:
            res = camera.resolution
        # the return values here need to be px, py, dz
        # these are the coordinates and dz for the resultant image.
        # Basically, what we need is an inverse projection from the fisheye
        # vectors back onto the plane.  arr_fisheye_vectors goes from px, py to
        # vector, and we need the reverse.
        # First, we transform lpos into *relative to the camera* coordinates.
        lpos = camera.position - pos
        lpos = lpos.dot(self.rotation_matrix)
        # lpos = lpos.dot(self.rotation_matrix)
        mag = (lpos * lpos).sum(axis=1)**0.5
        lpos /= mag[:, None]
        dz = mag / self.radius
        theta = np.arccos(lpos[:, 2])
        fov_rad = self.fov * np.pi / 180.0
        r = 2.0 * theta / fov_rad
        phi = np.arctan2(lpos[:, 1], lpos[:, 0])
        px = r * np.cos(phi)
        py = r * np.sin(phi)
        u = camera.focus.uq
        # dz is distance the ray would travel
        px = (px + 1.0) * res[0] / 2.0
        py = (py + 1.0) * res[1] / 2.0
        px = (u * np.rint(px)).astype("int64")
        py = (u * np.rint(py)).astype("int64")
        return px, py, dz


class SphericalLens(Lens):

    """docstring for SphericalLens"""

    def __init__(self):
        super(SphericalLens, self).__init__()
        self.radius = 1.0
        self.center = None
        self.rotation_matrix = np.eye(3)

    def setup_box_properties(self, camera):
        self.radius = camera.width.max()
        super(SphericalLens, self).setup_box_properties(camera)
        self.set_viewpoint(camera)

    def _get_sampler_params(self, camera, render_source):
        px = np.linspace(-np.pi, np.pi, camera.resolution[0],
                         endpoint=True)[:, None]
        py = np.linspace(-np.pi/2., np.pi/2., camera.resolution[1],
                         endpoint=True)[None, :]

        vectors = np.zeros((camera.resolution[0], camera.resolution[1], 3),
                           dtype='float64', order='C')
        vectors[:, :, 0] = np.cos(px) * np.cos(py)
        vectors[:, :, 1] = np.sin(px) * np.cos(py)
        vectors[:, :, 2] = np.sin(py)
        vectors = vectors * camera.width[0]

        positions = np.tile(camera.position, camera.resolution[0] * camera.resolution[1])\
                           .reshape(camera.resolution[0], camera.resolution[1], 3)

        R1 = get_rotation_matrix(0.5*np.pi, [1,0,0])
        R2 = get_rotation_matrix(0.5*np.pi, [0,0,1])
        uv = np.dot(R1, camera.unit_vectors)
        uv = np.dot(R2, uv)
        vectors.reshape((camera.resolution[0]*camera.resolution[1], 3))
        vectors = np.dot(vectors, uv)
        vectors.reshape((camera.resolution[0], camera.resolution[1], 3))

        if render_source.zbuffer is not None:
            image = render_source.zbuffer.rgba
        else:
            image = self.new_image(camera)

        dummy = np.ones(3, dtype='float64')
        image.shape = (camera.resolution[0]*camera.resolution[1], 1, 4)
        vectors.shape = (camera.resolution[0]*camera.resolution[1], 1, 3)
        positions.shape = (camera.resolution[0]*camera.resolution[1], 1, 3)

        sampler_params = dict(
            vp_pos=positions,
            vp_dir=vectors,
            center=self.back_center.d,
            bounds=(0.0, 1.0, 0.0, 1.0),
            x_vec=dummy,
            y_vec=dummy,
            width=np.zeros(3, dtype="float64"),
            image=image)
        return sampler_params

    def set_viewpoint(self, camera):
        """
        For a PerspectiveLens, the viewpoint is the front center.
        """
        self.viewpoint = camera.position

    def project_to_plane(self, camera, pos, res=None):
        if res is None:
            res = camera.resolution
        # Much of our setup here is the same as in the fisheye, except for the
        # actual conversion back to the px, py values.
        lpos = camera.position - pos
        # inv_mat = np.linalg.inv(self.rotation_matrix)
        # lpos = lpos.dot(self.rotation_matrix)
        mag = (lpos * lpos).sum(axis=1)**0.5
        lpos /= mag[:, None]
        # originally:
        #  the x vector is cos(px) * cos(py)
        #  the y vector is sin(px) * cos(py)
        #  the z vector is sin(py)
        # y / x = tan(px), so arctan2(lpos[:,1], lpos[:,0]) => px
        # z = sin(py) so arcsin(z) = py
        # px runs from -pi to pi
        # py runs from -pi/2 to pi/2
        px = np.arctan2(lpos[:, 1], lpos[:, 0])
        py = np.arcsin(lpos[:, 2])
        dz = mag / self.radius
        u = camera.focus.uq
        # dz is distance the ray would travel
        px = ((-px + np.pi) / (2.0*np.pi)) * res[0]
        py = ((-py + np.pi/2.0) / np.pi) * res[1]
        px = (u * np.rint(px)).astype("int64")
        py = (u * np.rint(py)).astype("int64")
        return px, py, dz

class StereoSphericalLens(Lens):

    """docstring for StereoSphericalLens"""

    def __init__(self):
        super(StereoSphericalLens, self).__init__()
        self.radius = 1.0
        self.center = None
        self.disparity = 0.
        self.rotation_matrix = np.eye(3)

    def setup_box_properties(self, camera):
        self.radius = camera.width.max()
        super(StereoSphericalLens, self).setup_box_properties(camera)
        self.set_viewpoint(camera)

    def _get_sampler_params(self, camera, render_source):
        self.disparity = camera.width[0].d / 1000.

        single_resolution_x = np.floor(camera.resolution[0])/2
        px = np.linspace(-np.pi, np.pi, single_resolution_x, endpoint=True)[:,None]
        py = np.linspace(-np.pi/2., np.pi/2., camera.resolution[1], endpoint=True)[None,:]

        vectors = np.zeros((single_resolution_x, camera.resolution[1], 3),
                           dtype='float64', order='C')
        vectors[:,:,0] = np.cos(px) * np.cos(py)
        vectors[:,:,1] = np.sin(px) * np.cos(py)
        vectors[:,:,2] = np.sin(py)
        vectors = vectors * camera.width[0]

        vectors2 = np.zeros((single_resolution_x, camera.resolution[1], 3),
                            dtype='float64', order='C')
        vectors2[:,:,0] = -np.sin(px) * np.ones((1, camera.resolution[1]))
        vectors2[:,:,1] = np.cos(px) * np.ones((1, camera.resolution[1]))
        vectors2[:,:,2] = 0

        positions = np.tile(camera.position, single_resolution_x * camera.resolution[1])\
                           .reshape(single_resolution_x, camera.resolution[1], 3)

        # The left and right are switched here since VR is in LHS.
        positions_left = positions + vectors2 * self.disparity
        positions_right = positions + vectors2 * (-self.disparity)

        R1 = get_rotation_matrix(0.5*np.pi, [1,0,0])
        R2 = get_rotation_matrix(0.5*np.pi, [0,0,1])
        uv = np.dot(R1, camera.unit_vectors)
        uv = np.dot(R2, uv)
        vectors.reshape((single_resolution_x*camera.resolution[1], 3))
        vectors = np.dot(vectors, uv)
        vectors.reshape((single_resolution_x, camera.resolution[1], 3))

        if render_source.zbuffer is not None:
            image = render_source.zbuffer.rgba
        else:
            image = self.new_image(camera)

        dummy = np.ones(3, dtype='float64')

        vectors_comb = np.vstack([vectors, vectors])
        positions_comb = np.vstack([positions_left, positions_right])

        image.shape = (camera.resolution[0]*camera.resolution[1], 1, 4)
        vectors_comb.shape = (camera.resolution[0]*camera.resolution[1], 1, 3)
        positions_comb.shape = (camera.resolution[0]*camera.resolution[1], 1, 3)

        sampler_params = dict(
            vp_pos=positions_comb,
            vp_dir=vectors_comb,
            center=self.back_center.d,
            bounds=(0.0, 1.0, 0.0, 1.0),
            x_vec=dummy,
            y_vec=dummy,
            width=np.zeros(3, dtype="float64"),
            image=image)
        return sampler_params

    def set_viewpoint(self, camera):
        """
        For a PerspectiveLens, the viewpoint is the front center.
        """
        self.viewpoint = camera.position

lenses = {'plane-parallel': PlaneParallelLens,
          'perspective': PerspectiveLens,
          'stereo-perspective': StereoPerspectiveLens,
          'fisheye': FisheyeLens,
          'spherical': SphericalLens,
          'stereo-spherical':StereoSphericalLens}
