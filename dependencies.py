"""Compute (some of) the transitive dependencies of a given file.

Currently it works with Python and Mako (html) files.

The way it works is by analyzing the imports and by analyzing function calls to
functions like open, GzipFile, etc. However, for this to work, the relevant
parameter must be a string, which often times is not the case.

So if in your code you have something like:

filename = 'foo'
open(filename)

then 'foo' won't be listed as a dependency.

A possible way to deal with this case is to install a watcher on the filesystem
when running the tests. However, that requires a non trivial effort, as the test
runner needs to be modified in order to store the accessed filenames.

"""
import ast
import collections
import fnmatch
import os
import pprint
import re
import sys


__all__ = ('transitive_dependencies',
           'python_dependencies',
           'html_dependencies')


class DependencyVisitor(ast.NodeVisitor):
    """Record the imports and call data from functions."""
    def __init__(self, functions=[]):
        super(DependencyVisitor, self).__init__()
        self.functions = functions
        self.modules = []
        self.filenames = []
        # In Python 3 absolute import is enabled by default
        self.absolute_import = sys.version_info == 3

    #def generic_visit(self, node):
    #    print type(node).__name__
    #    ast.NodeVisitor.generic_visit(self, node)

    def _extract_filename(self, function_name, args, keywords):
        """Extract a filename from a function call.

        It can only extract a filename if the argument is explicitly defined,
        that is if must be of type ast.Str.

        Args:
            function_name: str: the name of the current function
            args: list: ast nodes representing the function positional arguments
            keywords: list: ast nodes representing the keyword arguments

        Returns:
            the extracted filename
        """
        keywords = dict((k.arg, k.value) for k in keywords)
        for function_pattern, function_arg, post_processor in self.functions:
            if fnmatch.fnmatch(function_name, function_pattern):
                arg = None
                if isinstance(function_arg, basestring):
                    arg = keywords.get(function_arg)
                elif function_arg < len(args):
                    arg = args[function_arg]
                if isinstance(arg, ast.Str):
                    if post_processor:
                        return post_processor(arg.s)
                    else:
                        return arg.s

        return None

    def visit_Call(self, node):
        """Process a call and extract the filenames if any."""
        func = node.func
        func_name = None
        if isinstance(func, ast.Name):
            func_name = func.id
        elif isinstance(func, ast.Attribute):
            #print func.value, func.attr, func.ctx
            func_name = func.attr

        if func_name is None:
            return

        filename = self._extract_filename(func_name, node.args, node.keywords)
        if filename:
            self.filenames.append(filename)

    def visit_Import(self, node):
        """Process a regular import and store the name."""
        modules = [alias.name for alias in node.names]
        self.modules.extend(modules)

    def visit_ImportFrom(self, node):
        """Process a from import and store the possible imported modules.

        This may add some false positive entries to the modules list. This is
        because in the following statement:
            from foo import bar
        bar could be a module or a variable.

        So to be safe, we always add all names as submodules. In the example
        above, we would add both 'foo' and 'foo.bar' to the list.

        It also, sets the absolute_import value if it detects the statement:
            from __future__ import absolute_import
        """
        module = node.module
        names = [alias.name for alias in node.names]
        modules = [module] + ['%s.%s' % (module, name) for name in names]
        if module == '__future__' and 'absolute_import' in names:
            self.absolute_import = True
        self.modules.extend(modules)


def _extend_with_submodules(modules):
    """Return a set including all the submodules of the given modules."""
    all_modules = set()
    for module in modules:
        parts = module.split('.')
        for i in xrange(1, len(parts) + 1):
            submodule = '.'.join(parts[:i])
            all_modules.add(submodule)

    return all_modules


def _get_modules_filenames(modules, start_path='.'):
    """Convert modules to file paths, skipping not found ones.

    Args:
        modules: list: modules to find
        start_path: str: path where to search the modules

    Returns:
        list of filepaths representing the given modules. No error or warning
        is raised in case of non found modules.
    """
    filenames = []
    for module in modules:
        module_path = module.replace('.', os.sep)
        expected_path = os.path.join(start_path, module_path + '.py')
        if os.path.exists(expected_path):
            filenames.append(expected_path)
            continue
        # Check if module is a package
        expected_path = os.path.join(start_path, module_path, '__init__.py')
        if os.path.exists(expected_path):
            filenames.append(expected_path)

    return filenames

def _reachable(graph):
    """Return a dictionary with all reachable nodes from the graph nodes.

    Args:
        graph: dict: dictionary representing a graph. Keys are the nodes
        and values is a set containing the linked nodes.

    Returns:
        a new dictionary with the same keys, but whose values are all the
        reachable nodes from the current one.
    """
    reachable = {}
    for node in graph:
        reachable[node] = set(graph[node])
        # Add ourselves in case we were not already there.
        reachable[node].add(node)
        latest_nodes = reachable[node]
        while latest_nodes:
            new_nodes = set()
            for n in latest_nodes:
                new_nodes.update(graph[n])
            new_nodes -= reachable[node]
            reachable[node].update(new_nodes)
            latest_nodes = new_nodes

    return reachable


def python_dependencies(filename, start_path='.', functions=()):
    """Return the direct dependencies of a python file.

    It extracts the Python dependencies from the import statements. Non Python
    files are extracted from function calls as open, GzipFile, BZ2File, etc.
    Additionally calls to render are considered to be for templates.

    Args:
        filename: str: the filename of the python file
        start_path: str: path from where we should start searching for
        dependencies
        functions: tuple: functions to check when parsing the Python file.

    Returns:
        a set with all direct dependencies, including Python and plain files.
    """
    with open(filename) as f:
        node = ast.parse(f.read(), filename)
    visitor = DependencyVisitor(functions=functions)
        #functions=[
            #('open', 0, None),
            #('render', 0, lambda x: os.path.join('./templates', x.strip('/'))),
            #('GzipFile', 0, None),
            #('BZ2File', 0, None),
            #('ZipFile', 0, None),
            #('TarFile', 0, None),
            # CSV functions
            #('reader', 0, None),
            #('writer', 0, None),
            #('DictReader', 0, None),
            #('DictWriter', 0, None),
        #])
    visitor.visit(node)

    modules = visitor.modules
    modules = _extend_with_submodules(modules)
    modules_filenames = _get_modules_filenames(modules, start_path=start_path)

    return set(visitor.filenames + modules_filenames)


HTML_INCLUDE_RE = re.compile(r'file="([^"]+)"')


def html_dependencies(filename, template_path='./templates'):
    """Return the direct dependencies of a Mako template.

    Args:
        filename: str: the filename of the python file
        template_path: str: path where the templates are located

    Returns:
        a set with all direct HTML dependencies.
    """
    with open(filename) as f:
        content = f.read()
        includes = HTML_INCLUDE_RE.findall(content)
        normalized_includes = set()
        for include in includes:
            if include.startswith('..'):
                normalized_include = os.path.normpath(os.path.join(os.path.dirname(filename), include))
            else:
                normalized_include = os.path.join(template_path, include.strip('/'))
            normalized_includes.add(normalized_include)

        return normalized_includes


def transitive_dependencies(filenames):
    """Return a the transitive dependencies of the given filenames."""
    dependencies = {}
    processed_filenames = set()
    pending_filenames = set(filenames)
    while pending_filenames:
        filename = pending_filenames.pop()
        processed_filenames.add(filename)
        if filename.endswith('.py'):
            dependencies[filename] = python_dependencies(filename)
        elif filename.endswith('.html'):
            dependencies[filename] = html_dependencies(filename)
        else:
            dependencies[filename] = set([filename])
        pending_filenames.update(
            set(dependencies[filename]) - processed_filenames)

    return _reachable(dependencies)


def main(argv):
    deps = transitive_dependencies(argv[1:])
    pprint.pprint(deps)
    pprint.pprint(sorted([(k, len(v)) for k, v in deps.iteritems()],
                  key=lambda x: x[1]))


if __name__ == '__main__':
    sys.exit(main(sys.argv))
