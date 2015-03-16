import yt
import numpy as np
from yt.visualization.volume_rendering.api import BoxSource, CoordinateVectorSource

# Load the dataset.
ds = yt.load("Enzo_64/DD0043/data0043")
im, sc = yt.volume_render(ds, ('gas','density'))
sc.get_source(0).transfer_function.grey_opacity=True

dom = BoxSource(ds.domain_left_edge, ds.domain_right_edge, color=[1.]*4)
sc.add_source(dom)
im = sc.render()
im.write_png("%s_vr_domain.png" % ds)

#raise NotImplementedError("Something wrong with alpha blending here")
# Add the domain edges, with an alpha blending of 0.3:
# Add the grids, colored by the grid level with the algae colormap
for g in ds.index.grids:
    sc.add_source(BoxSource(g.LeftEdge, g.RightEdge, color=[1.]*4))
im = sc.render()
im.write_png("%s_vr_grids.png" % ds)

# Here we can draw the coordinate vectors on top of the image by processing
# it through the camera. Then save it out.
sc.add_source(CoordinateVectorSource(alpha=1.0))
im = sc.render()
im.write_png("%s_vr_coords.png" % ds)
