"""Interspace's own file-change tools for Claude sessions (multi-provider/providers.md, "Claude file tools").

Claude Code's Edit, Write and NotebookEdit resolve a path when they ask and write it later, following links,
so a sandboxed background command could swap a checked folder for a link in between. These replacements open
every step of the path from the workspace folder down, one `dir_fd` at a time with `O_NOFOLLOW` (folders also
`O_DIRECTORY`): a link anywhere on the path is refused, and a folder swapped after it was opened cannot redirect
the write. The new content goes to a temporary file in the same folder, renamed over the target through the
same folder descriptor, so the old file (even one hard-linked from outside) is replaced, never written through.

`locate` is lexical only: `..` and `.git` (any case) are refused, and the path must lie inside a task workspace.
Standard library only, Python 3.9 compatible.
"""
import json
import os
import secrets
import stat

MAX_PATH_CHARS = 4096
MAX_FILE_BYTES = 5 * 1024 * 1024
NEW_FILE_MODE = 0o644
NEW_FOLDER_MODE = 0o755
CELL_TYPES = ('code', 'markdown')
EDIT_MODES = ('replace', 'insert', 'delete')


class FileToolError(ValueError):
    """A refused or failed file change; the message is safe to show to the user and the model."""


def locate(path, workspaces, primary):
    """(project_id, workspace folder, path parts) for a file inside a task workspace, else None.

    Relative paths are in the primary workspace. The workspace folder is resolved (it is Interspace's own);
    nothing below it is: the parts are opened step by step without following links when the file is changed.
    """
    if not isinstance(path, str) or not path or len(path) > MAX_PATH_CHARS or '\x00' in path:
        return None
    if '..' in path.split('/'):
        return None
    if os.path.isabs(path):
        best = None
        for project_id, root in workspaces.items():
            for form in dict.fromkeys((os.path.normpath(root), os.path.realpath(root))):
                if path.startswith(form.rstrip('/') + '/') and (best is None or len(form) > len(best[2])):
                    best = (project_id, root, form)
        if best is None:
            return None
        project_id, root, form = best
        relative = path[len(form.rstrip('/')) + 1:]
    else:
        project_id = next((p for p, root in workspaces.items() if root == primary), None)
        if project_id is None:
            project_id = next((p for p, root in workspaces.items()
                               if os.path.realpath(root) == os.path.realpath(primary)), None)
        if project_id is None:
            return None
        root, relative = workspaces[project_id], path
    parts = tuple(part for part in relative.split('/') if part not in ('', '.'))
    if not parts or any(part.lower() == '.git' for part in parts):
        return None
    return project_id, os.path.realpath(root), parts


def _shown(parts):
    return '/'.join(parts)


def _open_folder(root, parts, create):
    """A descriptor of the folder `root/parts`, every step opened without following a link."""
    fd = os.open(root, os.O_RDONLY | os.O_DIRECTORY)
    try:
        for index, part in enumerate(parts):
            if create:
                try:
                    os.mkdir(part, NEW_FOLDER_MODE, dir_fd=fd)
                except FileExistsError:
                    pass
            try:
                child = os.open(part, os.O_RDONLY | os.O_DIRECTORY | os.O_NOFOLLOW, dir_fd=fd)
            except FileNotFoundError:
                raise FileToolError('The folder %s does not exist.' % _shown(parts[:index + 1])) from None
            except OSError:
                raise FileToolError('%s is not a folder inside the workspace (links are not followed).'
                                    % _shown(parts[:index + 1])) from None
            os.close(fd)
            fd = child
        return fd
    except BaseException:
        os.close(fd)
        raise


def _read(folder, name, shown):
    """(text, mode) of a regular file, or (None, None) when there is none."""
    try:
        fd = os.open(name, os.O_RDONLY | os.O_NOFOLLOW | os.O_NONBLOCK, dir_fd=folder)
    except FileNotFoundError:
        return None, None
    except OSError:
        raise FileToolError('%s is not a regular file inside the workspace (links are not followed).' % shown) from None
    try:
        info = os.fstat(fd)
        if not stat.S_ISREG(info.st_mode):
            raise FileToolError('%s is not a regular file.' % shown)
        if info.st_size > MAX_FILE_BYTES:
            raise FileToolError('%s is too large to change here.' % shown)
        chunks = []
        while True:
            chunk = os.read(fd, 1024 * 1024)
            if not chunk:
                break
            chunks.append(chunk)
    finally:
        os.close(fd)
    try:
        return b''.join(chunks).decode('utf-8'), stat.S_IMODE(info.st_mode)
    except UnicodeDecodeError:
        raise FileToolError('%s is not UTF-8 text.' % shown) from None


def _replace(folder, name, text, mode, shown):
    data = text.encode('utf-8')
    temporary = '.interspace-%s.tmp' % secrets.token_hex(8)
    fd = os.open(temporary, os.O_WRONLY | os.O_CREAT | os.O_EXCL | os.O_NOFOLLOW, 0o600, dir_fd=folder)
    try:
        try:
            view = memoryview(data)
            while view:
                view = view[os.write(fd, view):]
            os.fchmod(fd, mode)
            os.fsync(fd)
        finally:
            os.close(fd)
        os.rename(temporary, name, src_dir_fd=folder, dst_dir_fd=folder)
    except OSError:
        try:
            os.unlink(temporary, dir_fd=folder)
        except OSError:
            pass
        raise FileToolError('%s could not be written.' % shown) from None


def _change(target, create_folders, compute):
    """Open the folder, read the file, write `compute(old_text)` in its place; (old text or None, new text)."""
    _project, root, parts = target
    shown = _shown(parts)
    folder = _open_folder(root, parts[:-1], create_folders)
    try:
        old, mode = _read(folder, parts[-1], shown)
        new = compute(old, shown)
        if not isinstance(new, str) or len(new.encode('utf-8')) > MAX_FILE_BYTES:
            raise FileToolError('The new content of %s is too large.' % shown)
        _replace(folder, parts[-1], new, mode if mode is not None else NEW_FILE_MODE, shown)
        return old, new
    finally:
        os.close(folder)


def _text(value, label, allow_empty=True):
    if not isinstance(value, str) or (not allow_empty and not value):
        raise FileToolError(label + ' must be text.')
    if len(value) > MAX_FILE_BYTES:
        raise FileToolError(label + ' is too large.')
    return value


def write_file(target, content):
    """Create or overwrite a file, creating its folders."""
    content = _text(content, 'content')
    return _change(target, True, lambda old, shown: content)


def edit_file(target, old_string, new_string, replace_all=False):
    """Replace `old_string`, which must occur exactly once unless `replace_all`."""
    old_string = _text(old_string, 'old_string', allow_empty=False)
    new_string = _text(new_string, 'new_string')
    if old_string == new_string:
        raise FileToolError('old_string and new_string are the same.')

    def compute(old, shown):
        if old is None:
            raise FileToolError('%s does not exist. Use write_file to create it.' % shown)
        count = old.count(old_string)
        if count == 0:
            raise FileToolError('old_string was not found in %s.' % shown)
        if count > 1 and replace_all is not True:
            raise FileToolError('old_string occurs %d times in %s; give more context or set replace_all.'
                                % (count, shown))
        return old.replace(old_string, new_string)
    return _change(target, False, compute)


def edit_notebook(target, new_source, cell_id=None, cell_type=None, edit_mode='replace'):
    """Replace, insert (after `cell_id`, or first) or delete one cell of a Jupyter notebook."""
    new_source = _text(new_source, 'new_source')
    if edit_mode not in EDIT_MODES:
        raise FileToolError('edit_mode must be replace, insert or delete.')
    if cell_type is not None and cell_type not in CELL_TYPES:
        raise FileToolError('cell_type must be code or markdown.')
    if edit_mode == 'insert' and cell_type is None:
        raise FileToolError('Inserting a cell needs its cell_type.')
    if edit_mode != 'insert' and not isinstance(cell_id, str):
        raise FileToolError('Give the cell_id of the cell to change.')

    def compute(old, shown):
        if old is None:
            raise FileToolError('%s does not exist.' % shown)
        try:
            notebook = json.loads(old)
        except ValueError:
            raise FileToolError('%s is not a notebook.' % shown) from None
        cells = notebook.get('cells') if isinstance(notebook, dict) else None
        if not isinstance(cells, list):
            raise FileToolError('%s is not a notebook.' % shown)
        index = None
        if cell_id is not None:
            index = next((i for i, c in enumerate(cells) if isinstance(c, dict) and c.get('id') == cell_id), None)
            if index is None:
                raise FileToolError('%s has no cell %s.' % (shown, str(cell_id)[:80]))
        if edit_mode == 'delete':
            del cells[index]
        elif edit_mode == 'insert':
            cell = {'cell_type': cell_type, 'id': secrets.token_hex(4), 'metadata': {}, 'source': new_source}
            if cell_type == 'code':
                cell.update(outputs=[], execution_count=None)
            cells.insert(0 if index is None else index + 1, cell)
        else:
            cell = cells[index]
            cell['source'] = new_source
            if cell_type is not None:
                cell['cell_type'] = cell_type
            if cell.get('cell_type') == 'code':
                cell.update(outputs=[], execution_count=None)
            else:
                cell.pop('outputs', None)
                cell.pop('execution_count', None)
        return json.dumps(notebook, indent=1, ensure_ascii=False) + '\n'
    return _change(target, False, compute)
