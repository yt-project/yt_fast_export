"""
Volume rendering

"""

#-----------------------------------------------------------------------------
# Copyright (c) 2014, yt Development Team.
#
# Distributed under the terms of the Modified BSD License.
#
# The full license is in the file COPYING.txt, distributed with this software.
#-----------------------------------------------------------------------------


from .scene import Scene
from .camera import Camera
from .render_source import VolumeSource
from .transfer_functions import ProjectionTransferFunction
from .utils import data_source_or_all
from yt.funcs import mylog, iterable
from yt.utilities.lib.grid_traversal import \
        PartitionedGrid
import numpy as np


def off_axis_projection(data_source, center, normal_vector,
                        width, resolution, item,
                        weight=None, volume=None,
                        no_ghost=False, interpolated=False,
                        north_vector=None, num_threads=1, method='integrate'):
    r"""Project through a dataset, off-axis, and return the image plane.

    This function will accept the necessary items to integrate through a volume
    at an arbitrary angle and return the integrated field of view to the user.
    Note that if a weight is supplied, it will multiply the pre-interpolated
    values together, then create cell-centered values, then interpolate within
    the cell to conduct the integration.

    Parameters
    ----------
    data_source : `~yt.data_objects.api.Dataset`
        This is the dataset to volume render.
    center : array_like
        The current 'center' of the view port -- the focal point for the
        camera.
    normal_vector : array_like
        The vector between the camera position and the center.
    width : float or list of floats
        The current width of the image.  If a single float, the volume is
        cubical, but if not, it is left/right, top/bottom, front/back
    resolution : int or list of ints
        The number of pixels in each direction.
    item: string
        The field to project through the volume
    weight : optional, default None
        If supplied, the field will be pre-multiplied by this, then divided by
        the integrated value of this field.  This returns an average rather
        than a sum.
    volume : `yt.extensions.volume_rendering.AMRKDTree`, optional
        The volume to ray cast through.  Can be specified for finer-grained
        control, but otherwise will be automatically generated.
    no_ghost: bool, optional
        Optimization option.  If True, homogenized bricks will
        extrapolate out from grid instead of interpolating from
        ghost zones that have to first be calculated.  This can
        lead to large speed improvements, but at a loss of
        accuracy/smoothness in resulting image.  The effects are
        less notable when the transfer function is smooth and
        broad. Default: True
    interpolated : optional, default False
        If True, the data is first interpolated to vertex-centered data, 
        then tri-linearly interpolated along the ray. Not suggested for 
        quantitative studies.
    north_vector : optional, array_like, default None
        A vector that, if specified, restrics the orientation such that the 
        north vector dotted into the image plane points "up". Useful for rotations
    num_threads: integer, optional, default 1
        Use this many OpenMP threads during projection.
    method : string
        The method of projection.  Valid methods are:

        "integrate" with no weight_field specified : integrate the requested
        field along the line of sight.

        "integrate" with a weight_field specified : weight the requested
        field by the weighting field and integrate along the line of sight.

        "sum" : This method is the same as integrate, except that it does not
        multiply by a path length when performing the integration, and is
        just a straight summation of the field along the given axis. WARNING:
        This should only be used for uniform resolution grid datasets, as other
        datasets may result in unphysical images.
        or camera movements.
    Returns
    -------
    image : array
        An (N,N) array of the final integrated values, in float64 form.
    sc : Scene instance
        A Scene instance that was created and can be modified for further use.

    Examples
    --------

    >>> image, sc = off_axis_projection(ds, [0.5, 0.5, 0.5], [0.2,0.3,0.4],
                      0.2, N, "temperature", "density")
    >>> write_image(np.log10(image), "offaxis.png")

    """

    if method not in ['integrate','sum']:
        raise NotImplementedError("Only 'integrate' or 'sum' methods are valid for off-axis-projections")

    if interpolated == True:
        raise NotImplementedError("Only interpolated=False methods are currently implemented for off-axis-projections")

    data_source = data_source_or_all(data_source)
    sc = Scene()
    data_source.ds.index
    if item is None:
        field = data_source.pf.field_list[0]
        mylog.info('Setting default field to %s' % field.__repr__())

    vol = VolumeSource(data_source, item)
    ptf = ProjectionTransferFunction()
    vol.set_transfer_function(ptf)
    if weight is None:
        vol.set_fields([item])
    else:
        vol.set_fields([item, weight])
    camera = Camera(data_source)
    sc.set_default_camera(camera)
    sc.add_source(vol)

    camera.lens.set_camera(camera)
    vol.set_sampler(camera)
    assert (vol.sampler is not None)

    mylog.debug("Casting rays")
    total_cells = 0
    double_check = False
    if double_check:
        for brick in vol.volume.bricks:
            for data in brick.my_data:
                if np.any(np.isnan(data)):
                    raise RuntimeError

    ds = data_source.ds
    north_vector = camera.unit_vectors[0]
    east_vector = camera.unit_vectors[1]
    normal_vector = camera.unit_vectors[2]
    fields = vol.field 
    if not iterable(width):
        width = data_source.ds.arr([width]*3) 

    mi = ds.domain_right_edge.copy()
    ma = ds.domain_left_edge.copy()
    for off1 in [-1, 1]:
        for off2 in [-1, 1]:
            for off3 in [-1, 1]:
                this_point = (center + width[0]/2. * off1 * north_vector
                                     + width[1]/2. * off2 * east_vector
                                     + width[2]/2. * off3 * normal_vector)
                np.minimum(mi, this_point, mi)
                np.maximum(ma, this_point, ma)
    # Now we have a bounding box.
    data_source = ds.region(center, mi, ma)

    for i, (grid, mask) in enumerate(data_source.blocks):
        data = [(grid[field] * mask).astype("float64") for field in fields]
        pg = PartitionedGrid(
            grid.id, data,
            mask.astype('uint8'),
            grid.LeftEdge, grid.RightEdge, grid.ActiveDimensions.astype("int64"))
        grid.clear_data()
        vol.sampler(pg, num_threads = num_threads)

    image = vol.finalize_image(camera, vol.sampler.aimage)

    if method == "integrate":
        if weight is None:
            dl = width[2]
            image *= dl
        else:
            image[:,:,0] /= image[:,:,1]

    return image[:,:,0], sc
