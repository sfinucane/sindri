# -*- coding: utf-8 -*-
"""
    sindri.units
    ~~~~~~~~~~~~~~~~~~~~~~

    :description: Sindri library, Lantz unit extensions (Lantz uses Pint)

    ----
    
    TODO: Notify Pint about the following issue:    
    
    **MEGA-NOTE:**
    At this time, you MUST use ``lantz.Q_(<value>, <unit>)`` for the Quantity 
    to be created properly. If you use ``lantz.Q_('<value> <unit>')``, the 
    Quantity object is created as ``dimensionless`` and will not equate with
    the intended Quantities!

    :copyright: 2013 by Sindri Authors, see AUTHORS for more details.
    :license: LGPL, see LICENSE for more details.
"""
import sys
import pint
import lantz
import pkg_resources

# HACK: The following is a work-around to allow sindri to be used
# in scripts which are frozen into binary distributions by tools
# such as ``cx_freeze``. All sindri resources in a frozen application
# will be expected to reside in the ``/sindri`` sub-directory.
if hasattr(sys, "frozen"):
    def_fn = os.path.join(os.path.dirname(sys.executable), 
                        'sindri' , 'default_en.txt')
else:
    def_fn = pkg_resources.resource_filename(__name__, 'default_en.txt')
# END HACK 

_sindri_registry = pint.UnitRegistry(def_fn)
_lantz_registry = lantz.Q_._REGISTRY
lantz.Q_._REGISTRY = _sindri_registry
## bel, ``B`` is defined (as it is most common when using instruments)
#lantz.Q_._REGISTRY.define("bel = [logtenratio] = B")
## belmilliwatt, ``Bm`` (more commonly ``dBm`` is used)
#lantz.Q_._REGISTRY.define("belmilliwatt = [logtenratio_rel_mw] = Bm")

