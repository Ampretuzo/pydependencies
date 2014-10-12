import ast
import os.path
import tempfile
import textwrap
import unittest

import mock

import dependencies


class TestDependencyVisitor(unittest.TestCase):
    def test_absolute_import(self):
        node = ast.parse(
            'from __future__ import unicode_string, absolute_import')
        visitor = dependencies.DependencyVisitor()
        visitor.visit(node)
        self.assertTrue(visitor.absolute_import)

    def test_from_import(self):
        node = ast.parse(
            'from foo import bar')
        visitor = dependencies.DependencyVisitor()
        visitor.visit(node)
        # bar can be a module as well, so we need to assume it is.
        # A later step will filter it if it is not a module.
        self.assertEqual(['foo', 'foo.bar'], visitor.modules)

    def test_import(self):
        node = ast.parse(
            'import foo as bar')
        visitor = dependencies.DependencyVisitor()
        visitor.visit(node)
        self.assertEqual(['foo'], visitor.modules)

    def test_function_call_not_found(self):
        node = ast.parse(
            'open_file("foo.txt", "w")')
        visitor = dependencies.DependencyVisitor(functions=[('*open', 0, None)])
        visitor.visit(node)
        self.assertEqual([], visitor.filenames)

    def test_function_call_arg_not_found(self):
        node = ast.parse(
            'open("foo.txt", "w")')
        visitor = dependencies.DependencyVisitor(functions=[('*open', 2, None)])
        visitor.visit(node)
        self.assertEqual([], visitor.filenames)

    def test_function_call_arg_not_string(self):
        node = ast.parse(
            'open(filename, "w")')
        visitor = dependencies.DependencyVisitor(functions=[('*open', 0, None)])
        visitor.visit(node)
        self.assertEqual([], visitor.filenames)

    def test_function_call_exact(self):
        node = ast.parse(
            'open("foo.txt", "w")')
        visitor = dependencies.DependencyVisitor(functions=[('*open', 0, None)])
        visitor.visit(node)
        self.assertEqual(['foo.txt'], visitor.filenames)

    def test_function_call_approx(self):
        node = ast.parse(
            'gzip.gzopen("foo.gz", "w")')
        visitor = dependencies.DependencyVisitor(functions=[('*open', 0, None)])
        visitor.visit(node)
        self.assertEqual(['foo.gz'], visitor.filenames)

    def test_function_call_keyword(self):
        node = ast.parse(
            'open(x="foo.txt")')
        visitor = dependencies.DependencyVisitor(functions=[('*open', 'x', None)])
        visitor.visit(node)
        self.assertEqual(['foo.txt'], visitor.filenames)

    def test_function_call_keyword_not_found(self):
        node = ast.parse(
            'open(x="foo.txt")')
        visitor = dependencies.DependencyVisitor(functions=[('*open', 'y', None)])
        visitor.visit(node)
        self.assertEqual([], visitor.filenames)


class TestDependenciesUtils(unittest.TestCase):
    def test_extend_with_submodules(self):
        extended_deps = dependencies._extend_with_submodules(
            ['foo.bar', 'foo.foo.baz'])

        self.assertEqual(set(('foo', 'foo.bar', 'foo.foo', 'foo.foo.baz')),
                         extended_deps)

    def test_reachable(self):
        graph = {
            'a': set('b'),
            'b': set('c'),
            'c': set('d'),
            'd': set(),
        }
        reachable_nodes = dependencies._reachable(graph)
        expected_nodes = {
            'a': set('abcd'),
            'b': set('bcd'),
            'c': set('cd'),
            'd': set('d')
        }
        self.assertEqual(expected_nodes, reachable_nodes)

    def test_reachable_with_cycle(self):
        graph = {
            'a': set('b'),
            'b': set('c'),
            'c': set('d'),
            'd': set('a'),
        }
        reachable_nodes = dependencies._reachable(graph)
        expected_nodes = {
            'a': set('abcd'),
            'b': set('abcd'),
            'c': set('abcd'),
            'd': set('abcd')
        }
        self.assertEqual(expected_nodes, reachable_nodes)

    def test_get_modules_filenames(self):
        filenames = {
            os.path.join('start', 'foo.py'): False,
            os.path.join('start', 'foo', '__init__.py'): True,
            os.path.join('start', 'foo', 'bar.py'): False,
            os.path.join('start', 'foo', 'bar', '__init__.py'): True,
            os.path.join('start', 'foo', 'bar', 'baz.py'): True,
            # Note that start/foo/bar/baz/__init__ is not defined as it should
            # not be called.
            os.path.join('start', 'unexistent', 'foo.py'): False,
            os.path.join('start', 'unexistent', 'foo', '__init__.py'): False,
            os.path.join('start', 'unexistent', '__init__.py'): False,
            os.path.join('start', 'unexistent.py'): False,
        }

        expected_filenames = [k for (k, v) in filenames.iteritems() if v]
        with mock.patch('os.path.exists', side_effect=lambda x: filenames[x]):
            filenames = dependencies._get_modules_filenames(
                ['foo.bar.baz', 'foo.bar', 'foo', 'unexistent.foo', 'unexistent'],
                start_path='start')
        self.assertItemsEqual(expected_filenames, filenames)

    def test_html_dependencies(self):
        content = """
        <html>
            <%inherit file="/base.html"/>
            <%include file="header.html"/>
                hello world
            <%include file="../footer.html"/>
        </html>
        """
        expected_deps = set((
            os.path.join('start', 'base.html'),
            os.path.join('start', 'header.html'),
            os.path.join(os.path.dirname(tempfile.gettempdir()), 'footer.html'),
        ))
        with tempfile.NamedTemporaryFile(suffix='.html') as temp:
            temp.write(content)
            temp.seek(0)
            deps = dependencies.html_dependencies(temp.name,
                                                  template_path='start')
            self.assertEqual(expected_deps, deps)

    def test_python_dependencies(self):
        content = textwrap.dedent("""
            from foo import bar
            import bar
            import os

            open('foo.txt')
            csv.reader('foo.csv')
        """)
        expected_deps = set((
            os.path.join('start', 'foo', 'bar.py'),
            os.path.join('start', 'bar.py'),
            os.path.join('foo.txt'),
            os.path.join('foo.csv'),
        ))
        filenames = {
            os.path.join('start', 'foo', 'bar.py'): True,
            os.path.join('start', 'bar.py'): True,
        }

        with mock.patch('os.path.exists',
                        side_effect=lambda x: filenames.get(x, False)), \
                tempfile.NamedTemporaryFile(suffix='.py') as temp:
            temp.write(content)
            temp.seek(0)
            deps = dependencies.python_dependencies(
                temp.name, start_path='start',
                functions=(('open', 0, None), ('reader', 0, None)))
            self.assertEqual(expected_deps, deps)

    def test_transitive_dependencies(self):
        filenames = ['a.py', 'b.py', 'a.html', 'a.txt']
        deps = {
            'a.py': ['b.py', 'a.txt'],
            'b.py': ['c.py'],
            'c.py': [],
            'a.html': [],
            'a.txt': []
        }
        expected_deps = dependencies._reachable(deps)
        with mock.patch('dependencies.python_dependencies', side_effect=lambda x: set(deps.get(x, []))), \
                mock.patch('dependencies.html_dependencies', side_effect=lambda x: set(deps.get(x, []))):
            transitive_deps = dependencies.transitive_dependencies(filenames)
        self.assertEqual(expected_deps, transitive_deps)
