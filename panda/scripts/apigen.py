#!/usr/bin/env python

import os
import sys
import re
import pdb
import pycparser
import subprocess

KNOWN_TYPES = ['int', 'double', 'float', 'char', 'short', 'long',
               'uint8_t', 'uint16_t', 'uint32_t', 'uint64_t']


# input is name of interface file.
# output is list of args for that fn.
# so, for the fn
# void taint2_labelset_llvm_iter(int reg_num, int offset, int (*app)(uint32_t el, void *stuff1), void *stuff2);
# this will return
# ["reg_num", "offset", "app", "stuff2"]
#
def get_arglists(pf):
#    pyf = subprocess.check_output( ("gcc -E " + prototype_file).split())
    pyc = pycparser.CParser()
    p = pyc.parse(pf)
    args = {}
    for (dc, d) in p.children():
        if type(d) == pycparser.c_ast.Decl:
            # a prototype
            function_name = d.name
            #print "function name = [%s]" % function_name
            fundec = d.children()[0][1]
            args[function_name] = []
            for arg in fundec.args.params:
                if not (arg.name is None):
                    args[function_name].append(arg.name)
    return args


# prototype_line is a string containint a c function prototype.
# all on one line.  has to end with a semi-colon.
# return type has to be simple (better not return a fn ptr).
# it can return a pointer to something.
# this fn splits that line up into 
# return_type,
# fn name
# fn args (with types)
def split_fun_prototype(prototype_line):
    foo = re.search("^([^(]+)\((.*)\)\s*\;", prototype_line)
    if foo is None:
        return None
    (a,fn_args_with_types) = foo.groups()
    bar = a.split()
    fn_name = bar[-1]
    fn_type = " ".join(bar[0:-1])
    # carve off ptrs from head of fn name
    while fn_name[0] == '*':
        fn_name = fn_name[1:]
        fn_type = fn_type + " *"
    return (fn_type, fn_name, fn_args_with_types)


def generate_code(functions, module, includes):
    code =  "#ifndef __%s_EXT_H__\n" % (module.upper())
    code += "#define __%s_EXT_H__\n" % (module.upper())
    code +="""
/*
 * DO NOT MODIFY. This file is automatically generated by scripts/apigen.py,
 * based on the <plugin>_int.h file in your plugin directory.
 */

#include <dlfcn.h>
#include "panda/plugin.h"

"""
#    for include in includes:
#        code+= include + "\n"

    for (fn_rtype, fn_name, fn_args_with_types, fn_args_list) in functions:
        fn_args = ",".join(fn_args_list)
        code+= "typedef " + fn_rtype + "(*" + fn_name + "_t)(" + fn_args_with_types + ");\n"
        code+= "static " + fn_name + "_t __" + fn_name + " = NULL;\n"
        code += "static inline " + fn_rtype + " " + fn_name + "(" + fn_args_with_types + ");\n"
        code += "static inline " + fn_rtype + " " + fn_name + "(" + fn_args_with_types + "){\n"
        code += "    assert(__" + fn_name + ");\n"
        code += "    return __" + fn_name + "(" + fn_args + ");\n"
        code += "}\n"

    code += "#define API_PLUGIN_NAME \"" + module
    code += """\"\n#define IMPORT_PPP(module, func_name) { \\
 __##func_name = (func_name##_t) dlsym(module, #func_name); \\
 char *err = dlerror(); \\
 if (err) { \\
    printf("Couldn't find %s function in library %s.\\n", #func_name, API_PLUGIN_NAME); \\
    printf("Error: %s\\n", err); \\
    return false; \\
 } \\
}
"""
    code += "static inline bool init_%s_api(void);" % module
    code += "static inline bool init_%s_api(void){" % module


    code += """
    void *module = panda_get_plugin_by_name("panda_" API_PLUGIN_NAME ".so");
    if (!module) {
        printf("In trying to add plugin, couldn't load %s plugin\\n", API_PLUGIN_NAME);
        return false;
    }
    dlerror();
""" 

    for (fn_rtype, fn_name, fn_args_with_types, fn_args_list) in functions:
        code += "IMPORT_PPP(module, " + fn_name + ")\n"

    code += """return true;
}

#undef API_PLUGIN_NAME
#undef IMPORT_PPP

#endif
"""

    return code

bad_keywords = ['static', 'inline']
keep_keywords = ['const', 'unsigned']
def resolve_type(modifiers, name):
    modifiers = modifiers.strip()
    tokens = modifiers.split()
    if len(tokens) > 1:
        # we have to go through all the keywords we care about
        relevant = []
        for token in tokens[:-1]:
            if token in keep_keywords:
                relevant.append(token)
            if token in bad_keywords:
                raise Exception("Invalid token in API function definition")
        relevant.append(tokens[-1])
        rtype = " ".join(relevant)
    else:
        rtype = tokens[0]
    if name.startswith('*'):
        return rtype+'*', name[1:]
    else:
        return rtype, name

def generate_api(plugin_name, plugin_dir):
    if ("%s_int.h" % plugin_name) not in os.listdir(plugin_dir):
        return


    print "Building API for plugin " + plugin_name,
    functions = []
    includes = []

    interface_file = os.path.join(plugin_dir, '{0}_int.h'.format(plugin_name))

    # use preprocessor 
    pf = subprocess.check_output( ("gcc -E " + interface_file).split())


    # use pycparser to get arglists
    arglist = get_arglists(pf)

    for line in pf.split("\n"):
        line = line.strip();
        if line and not line.startswith('#') and not (re.match("^/", line)):
            # not a typedef and not a comment.
            # could be a fn prototype
            #print line
            foo = split_fun_prototype(line)
            if not (foo is None):
                # it is a fn prototype -- pull out return type, name, and arglist with types
                (fn_rtype, fn_name, args_with_types) = foo
                tup = (fn_rtype, fn_name, args_with_types, arglist[fn_name])
                functions.append(tup)
    code = generate_code(functions, plugin_name, includes)
    with open(os.path.join(plugin_dir, '{0}_ext.h'.format(plugin_name)), 'w') as extAPI:
        extAPI.write(code)
    print "... Done!"


# the directory this script is in
script_dir = os.path.dirname(os.path.realpath(__file__))
# which means this is the plugins dir
plugins_dir = os.path.realpath(script_dir + "/../plugins")

# iterate over enabled plugins
plugins = (open(plugins_dir + "/config.panda").read()).split()
for plugin in plugins:
    #print plugin
    if plugin[0] == '#':
        continue
    plugin_dir = plugins_dir + "/" + plugin
    generate_api(plugin, plugin_dir)
