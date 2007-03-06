"""
Deliverator
===========

    The Deliverator is a TurboGears-based system for querying and displaying
    images.  Images are dumped from Raven into local, web-accessible storage space,
    and then metadata about those images is submitted to The Deliverator.  The user
    (you) then goes to the Deliverator website and views those plots.

@author: U{Matthew Turk<http://www.stanford.edu/~mturk/>}
@organization: U{KIPAC<http://www-group.slac.stanford.edu/KIPAC/>}
@contact: U{mturk@slac.stanford.edu<mailto:mturk@slac.stanford.edu>}
"""

from yt.deliverator import *

# First we snag the API key

import os, cPickle, sys, StringIO, base64

if ytcfg.has_option("Deliverator","api-key"):
    APIKey=ytcfg.get("Deliverator","api-key")
else:
    APIKey = None
    mylog.warning("No API Key Found!  All actions will fail.")


def SubmitRun(metaData, user):
    """
    Submits run information to The Deliverator server.  Returns the RunID

    @param metaData: whatever string you want to use to identify this run
    @type metaData: string
    @param user: the user submitting the run.  Linked with The Deliverator server.
    @type user: string (deliverator user)
    @return: the ID either for the new run, or the existing run the metaData matches
    """
    if not APIKey:
        return
    loc = DeliveratorServerLocator()
    port = loc.getraven_porttype()
    req = SubmitNewRunInput()
    req.APIKey = APIKey
    req.User = user
    req.MetaData = metaData
    resp=port.SubmitNewRun(req)
    mylog.info("RunID: %s (%s)", resp.RunID, resp.Response)
    return resp.RunID, resp.Response

def SubmitParameterFile(RunID, hierarchy):
    """
    Submits the parameter file to The Deliverator server.  Returns the response.

    @param RunID: identifier for the broader "run"
    @type RunID: integer
    @param hierarchy: instance you're submitting
    @type hierarchy: L{EnzoHierarchy<EnzoHierarchy>}
    @return: text response from Deliverator
    """
    if not APIKey:
        return
    loc = DeliveratorServerLocator()
    port = loc.getraven_porttype()
    req = SubmitNewParameterFileInput()
    req.APIKey = APIKey
    req.GeneratedAt = hierarchy["CurrentTimeIdentifier"]
    req.RunID = RunID
    req.FileName = hierarchy.parameterFilename
    #req.metaData = hierarchy["MetaDataString"]
    old_stdout = sys.stdout
    k = StringIO.StringIO()
    sys.stdout = k
    hierarchy.printStats()
    req.MetaData = k.getvalue()
    #print req.MetaData
    sys.stdout = old_stdout
    t = hierarchy.parameters.copy()
    t.update(hierarchy.conversionFactors.copy())
    t.update(hierarchy.units.copy())
    req.PickleObj = base64.b64encode(cPickle.dumps(t))
    resp=port.SubmitNewParameterFile(req)
    mylog.info("%s (%s)", req.FileName, resp.Response)
    return resp.Response
    
def SubmitImage(hierarchy, img_info):
    """
    Submits the parameter file to The Deliverator server.  Returns the response.

    @param hierarchy: instance you're submitting from
    @type hierarchy: L{EnzoHierarchy<EnzoHierarchy>}
    @param img_info: info for the image submission
    @type img_info: dict
    @return: text response from Deliverator
    """
    if not APIKey:
        return
    loc = DeliveratorServerLocator()
    port = loc.getraven_porttype()
    req = SubmitNewImageInput()
    req.APIKey = APIKey
    req.IMG_src = img_info["Filename"]
    req.Field1 = img_info["FieldList"][0]
    if len(img_info["FieldList"])>1:
        req.Field2 = img_info["FieldList"][1]
    if len(img_info["FieldList"])>2:
        req.Field3 = img_info["FieldList"][2]
    if img_info.has_key("Axis"):
        req.Axis = img_info["Axis"]
    else:
        req.Axis = "None"
    req.Unit = img_info["Unit"]
    req.Width = img_info["Width"]
    req.ParameterFile = hierarchy["CurrentTimeIdentifier"]
    req.Type = img_info["Type"]
    req.RunID = img_info["RunID"]
    resp=port.SubmitNewImage(req)
    mylog.info("%s (%s)", req.IMG_src, resp.Response)
    return resp.Response
