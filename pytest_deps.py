"""Py.test plugin to smartly run only tests whose result may have changed.

It works by inferring a dependency graph of the sources. Note that as this
graph is inferred tehre may be many edge cases in which one or more sources are
not discovered.

See the dependencies module for more details.
"""
import gitlint

import dependencies


def pytest_addoption(parser):
    """Register the options for py.test."""
    group = parser.getgroup('dependencies',
                            'run only tests affected by the changed files')
    group._addoption('--affected',
        action='store_true',
        dest='dependencies',
        default=False,
        help='run only tests affected by the changed files')
    group._addoption('--base_path',
        action='store',
        dest='base_path',
        default='.',
        help='base path where the source is found')
    group._addoption('--templates_path',
        action='store',
        dest='templates_path',
        default='templates',
        help='path of the templates folder relative to base_path')


def pytest_report_header(config):
    """Print a message in case the plugin is activated."""
    if config.option.dependencies:
        return 'Only tests affected by the changed files are being run.'


def get_modified_filenames():
    """Return a set with the filename of the modified files."""
    vcs, unused_root = gitlint.get_vcs_root()
    if not vcs:
        return None

    return set(vcs.modified_filenames().iterkeys())


def pytest_collection_modifyitems(session, config, items):
    """Remove those tests which do not depend on the modified files."""
    modified_filenames = get_modified_filenames()
    if modified_filenames is None:
        print 'Only git and mercurial are supported. No tests were filtered'
        return

    test_filenames = set(str(item.fspath) for item in items)
    all_deps = dependencies.transitive_dependencies(test_filenames)

    # item.fspath could be None, so adding it to the list of filenames which we
    # need to check no matter what.
    required_filenames = set(['None'])
    for filename in test_filenames:
        if (filename in modified_filenames or
                all_deps[filename].intersection(modified_filenames)):
            required_filenames.add(filename)

    new_items = [item for item in items
                 if str(item.fspath) in required_filenames]

    items[:] = new_items
