##
# @file   Params.py
# @author Yibo Lin
# @date   Apr 2018
# @brief  User parameters
#

import os
import sys
import copy
import json 
import logging
import math 
from collections import OrderedDict
import pdb

# Global (non-RUPlace) DREAMPlace keys that the s14-calibrated RUPlace congestion
# preset needs.  The ruplace_* half of the preset lives in the params.json
# defaults; this is the rest.  It is applied ONLY when ``ruplace_flag`` is set,
# only when ``ruplace_preset`` names it, and only to keys the user did not spell
# out in the JSON -- so plain DREAMPlace (ruplace_flag 0) is byte-identical.
RUPLACE_PRESETS = {
    "congestion": OrderedDict([
        ("target_density", 1.0),
        ("gamma", 0.92),
        ("gp_noise_ratio", 0.03),
        ("stop_overflow", 0.10),
        ("legalize_flag", 1),
        ("num_bins_x", 512),
        ("num_bins_y", 512),
        ("global_place_stages", [
            {
                "num_bins_x": 512,
                "num_bins_y": 512,
                "iteration": 1000,
                "learning_rate": 0.01,
                "wirelength": "weighted_average",
                "optimizer": "nesterov",
            }
        ]),
    ]),
}


class Params:
    """
    @brief Parameter class
    """
    def __init__(self):
        """
        @brief initialization
        """
        filename = os.path.join(os.path.dirname(__file__), 'params.json')
        self.__dict__ = {}
        params_dict = {}
        with open(filename, "r") as f:
            params_dict = json.load(f, object_pairs_hook=OrderedDict)
        for key, value in params_dict.items():
            if 'default' in value: 
                self.__dict__[key] = value['default']
            else:
                self.__dict__[key] = None
        self.__dict__['params_dict'] = params_dict

    def printWelcome(self):
        """
        @brief print welcome message
        """
        content = """\
========================================================
                       DREAMPlace
            Yibo Lin (http://yibolin.com)
   David Z. Pan (http://users.ece.utexas.edu/~dpan)
========================================================"""
        print(content)

    def printHelp(self):
        """
        @brief print help message for JSON parameters
        """
        content = self.toMarkdownTable()
        print(content)

    def toMarkdownTable(self):
        """
        @brief convert to markdown table 
        """
        key_length = len('JSON Parameter')
        key_length_map = []
        default_length = len('Default')
        default_length_map = []
        description_length = len('Description')
        description_length_map = []

        def getDefaultColumn(key, value):
            if sys.version_info.major < 3: # python 2
                flag = isinstance(value['default'], unicode)
            else: #python 3
                flag = isinstance(value['default'], str)
            if flag and not value['default'] and 'required' in value: 
                return value['required']
            else:
                return value['default']

        for key, value in self.params_dict.items():
            key_length_map.append(len(key))
            default_length_map.append(len(str(getDefaultColumn(key, value))))
            description_length_map.append(len(value.get('description', '')))
            key_length = max(key_length, key_length_map[-1])
            default_length = max(default_length, default_length_map[-1])
            description_length = max(description_length, description_length_map[-1])

        content = "| %s %s| %s %s| %s %s|\n" % (
                'JSON Parameter', 
                " " * (key_length - len('JSON Parameter') + 1), 
                'Default', 
                " " * (default_length - len('Default') + 1), 
                'Description', 
                " " * (description_length - len('Description') + 1)
                )
        content += "| %s | %s | %s |\n" % (
                "-" * (key_length + 1), 
                "-" * (default_length + 1), 
                "-" * (description_length + 1)
                )
        count = 0
        for key, value in self.params_dict.items():
            content += "| %s %s| %s %s| %s %s|\n" % (
                    key, 
                    " " * (key_length - key_length_map[count] + 1), 
                    str(getDefaultColumn(key, value)), 
                    " " * (default_length - default_length_map[count] + 1), 
                    value.get('description', ''), 
                    " " * (description_length - description_length_map[count] + 1)
                    )
            count += 1
        return content 

    def toJson(self):
        """
        @brief convert to json
        """
        data = {}
        for key, value in self.__dict__.items():
            if key != 'params_dict': 
                data[key] = value
        return data

    def fromJson(self, data):
        """
        @brief load form json
        """
        for key, value in data.items(): 
            self.__dict__[key] = value
        self.applyRuplacePreset(data.keys())

    def applyRuplacePreset(self, user_keys=()):
        """
        @brief apply the global-key half of the RUPlace preset

        Enabling RUPlace with nothing but ``routability_opt_flag`` and
        ``ruplace_flag`` must reproduce the calibrated flow, so the non-RUPlace
        DREAMPlace keys that calibration depends on are filled in here.  The
        preset runs only when ``ruplace_flag`` is set and ``ruplace_preset``
        names a known preset ("none" disables it); keys the user spelled out in
        the JSON always win, and every value actually changed is logged at INFO.
        @param user_keys keys given explicitly by the user, never overridden
        @return list of keys the preset changed
        """
        if not int(self.__dict__.get("ruplace_flag", 0) or 0):
            return []
        name = str(self.__dict__.get("ruplace_preset", "none") or "none").strip().lower()
        if name in ("", "none"):
            return []
        preset = RUPLACE_PRESETS.get(name)
        if preset is None:
            logging.warning("unknown ruplace_preset %r; no preset applied", name)
            return []
        user_keys = set(user_keys)
        applied = []
        for key, value in preset.items():
            if key in user_keys:
                continue
            old = self.__dict__.get(key)
            if old == value:
                continue
            self.__dict__[key] = copy.deepcopy(value)
            applied.append(key)
            logging.info("RUPlace preset '%s': %s %s -> %s" % (name, key, old, value))
        return applied

    def dump(self, filename):
        """
        @brief dump to json file
        """
        with open(filename, 'w') as f:
            json.dump(self.toJson(), f)

    def load(self, filename):
        """
        @brief load from json file
        """
        with open(filename, 'r') as f:
            self.fromJson(json.load(f))

    def __str__(self):
        """
        @brief string
        """
        return str(self.toJson())

    def __repr__(self):
        """
        @brief print
        """
        return self.__str__()

    def design_name(self):
        """
        @brief speculate the design name for dumping out intermediate solutions 
        """
        if self.aux_input: 
            design_name = os.path.basename(self.aux_input).replace(".aux", "").replace(".AUX", "")
        elif self.verilog_input:
            design_name = os.path.basename(self.verilog_input).replace(".v", "").replace(".V", "")
        elif self.def_input: 
            design_name = os.path.basename(self.def_input).replace(".def", "").replace(".DEF", "")
        return design_name 

    def solution_file_suffix(self): 
        """
        @brief speculate placement solution file suffix 
        """
        if self.def_input is not None and os.path.exists(self.def_input): # LEF/DEF 
            return "def"
        else: # Bookshelf
            return "pl"
