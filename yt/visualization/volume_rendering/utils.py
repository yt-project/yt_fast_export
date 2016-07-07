import numpy as np
from yt.data_objects.static_output import Dataset
from yt.utilities.lib import bounding_volume_hierarchy
from yt.utilities.lib.grid_traversal import \
    VolumeRenderSampler, InterpolatedProjectionSampler, ProjectionSampler

from yt.utilities.on_demand_imports import NotAModule
try:
    from yt.utilities.lib import mesh_traversal
except ImportError:
    mesh_traversal = NotAModule("pyembree")

def data_source_or_all(data_source):
    if isinstance(data_source, Dataset):
        data_source = data_source.all_data()
    return data_source


def new_mesh_sampler(camera, render_source, engine):
    params = ensure_code_unit_params(camera._get_sampler_params(render_source))
    args = (
        np.atleast_3d(params['vp_pos']),
        np.atleast_3d(params['vp_dir']),
        params['center'],
        params['bounds'],
        np.atleast_3d(params['image']).astype('float64'),
        params['x_vec'],
        params['y_vec'],
        params['width'],
    )
    kwargs = {'lens_type': params['lens_type']}
    if engine == 'embree':
        sampler = mesh_traversal.EmbreeMeshSampler(*args, **kwargs)
    elif engine == 'yt':
        sampler = bounding_volume_hierarchy.BVHMeshSampler(*args, **kwargs)
    return sampler


def new_volume_render_sampler(camera, render_source):
    params = ensure_code_unit_params(camera._get_sampler_params(render_source))
    params.update(transfer_function=render_source.transfer_function)
    params.update(transfer_function=render_source.transfer_function)
    params.update(num_samples=render_source.num_samples)
    args = (
        np.atleast_3d(params['vp_pos']),
        np.atleast_3d(params['vp_dir']),
        params['center'],
        params['bounds'],
        params['image'],
        params['x_vec'],
        params['y_vec'],
        params['width'],
        params['transfer_function'],
        params['num_samples'],
    )
    kwargs = {'lens_type': params['lens_type']}
    if "camera_data" in params:
        kwargs['camera_data'] = params['camera_data']
    if render_source.zbuffer is not None:
        kwargs['zbuffer'] = render_source.zbuffer.z
        args[4][:] = np.reshape(render_source.zbuffer.rgba[:], \
            (camera.resolution[0], camera.resolution[1], 4))
    else:
        kwargs['zbuffer'] = np.ones(params['image'].shape[:2], "float64")

    sampler = VolumeRenderSampler(*args, **kwargs)
    return sampler


def new_interpolated_projection_sampler(camera, render_source):
    params = ensure_code_unit_params(camera._get_sampler_params(render_source))
    params.update(transfer_function=render_source.transfer_function)
    params.update(num_samples=render_source.num_samples)
    args = (
        np.atleast_3d(params['vp_pos']),
        np.atleast_3d(params['vp_dir']),
        params['center'],
        params['bounds'],
        params['image'],
        params['x_vec'],
        params['y_vec'],
        params['width'],
        params['num_samples'],
    )
    kwargs = {'lens_type': params['lens_type']}
    if render_source.zbuffer is not None:
        kwargs['zbuffer'] = render_source.zbuffer.z
    else:
        kwargs['zbuffer'] = np.ones(params['image'].shape[:2], "float64")
    sampler = InterpolatedProjectionSampler(*args, **kwargs)
    return sampler


def new_projection_sampler(camera, render_source):
    params = ensure_code_unit_params(camera._get_sampler_params(render_source))
    params.update(transfer_function=render_source.transfer_function)
    params.update(num_samples=render_source.num_samples)
    args = (
        np.atleast_3d(params['vp_pos']),
        np.atleast_3d(params['vp_dir']),
        params['center'],
        params['bounds'],
        params['image'],
        params['x_vec'],
        params['y_vec'],
        params['width'],
        params['num_samples'],
    )
    kwargs = {'lens_type': params['lens_type']}
    if render_source.zbuffer is not None:
        kwargs['zbuffer'] = render_source.zbuffer.z
    else:
        kwargs['zbuffer'] = np.ones(params['image'].shape[:2], "float64")
    sampler = ProjectionSampler(*args, **kwargs)
    return sampler

def get_corners(le, re):
    return np.array([
        [le[0], le[1], le[2]],
        [re[0], le[1], le[2]],
        [re[0], re[1], le[2]],
        [le[0], re[1], le[2]],
        [le[0], le[1], re[2]],
        [re[0], le[1], re[2]],
        [re[0], re[1], re[2]],
        [le[0], re[1], re[2]],
        ], dtype='float64')
