# coding: utf-8
import re
from datetime import datetime
import sublime
from sublime_plugin import TextCommand, WindowCommand

from .util import find_view_by_settings
from .cmd import GitCmd


GIT_BLAME_TITLE_PREFIX = '*git-blame*: '
GIT_BLAME_SYNTAX = 'Packages/SublimeGit/SublimeGit Blame.tmLanguage'


class GitBlameCommand(WindowCommand, GitCmd):
    """
    Documentation coming soon.
    """

    def file_in_git(self, filename):
        return self.git_exit_code(['ls-files', filename, '--error-unmatch']) == 0

    def run(self, filename=None, revision=None):
        # check if file is saved
        filename = filename if filename else self.window.active_view().file_name()
        if not filename:
            sublime.error_message('Cannot do git-blame on unsaved files.')
            return

        # check if file is known to git
        in_git = self.file_in_git(filename)
        if not in_git:
            sublime.error_message('The file %s is not tracked by git.' % filename)
            return

        repo = self.get_repo(self.window)
        if repo:
            title = GIT_BLAME_TITLE_PREFIX + filename.replace(repo, '').lstrip('/\\')
            if revision:
                title = '%s @ %s' % (title, revision[:8])
            view = find_view_by_settings(self.window, git_view='blame', git_repo=repo,
                                         git_blame_file=filename, git_blame_rev=revision)

            if not view:
                view = self.window.new_file()
                view.set_name(title)
                view.set_scratch(True)
                view.set_read_only(True)
                view.set_syntax_file(GIT_BLAME_SYNTAX)

                view.settings().set('word_wrap', False)
                view.settings().set('git_view', 'blame')
                view.settings().set('git_repo', repo)
                view.settings().set('git_blame_file', filename)
                view.settings().set('git_blame_rev', revision)

            view.run_command('git_blame_refresh', {'filename': filename, 'revision': revision})


class GitBlameRefreshCommand(TextCommand, GitCmd):

    HEADER_RE = re.compile(r'^(?P<sha>[0-9a-f]{40}) (\d+) (\d+) ?(\d+)?$')

    def parse_commit_line(self, commitline):
        fieldname, value = commitline.split(' ', 1)
        value = value.strip()
        if fieldname in ('committer-time', 'author-time'):
            value = int(value)
        elif fieldname in ('committer-mail', 'author-mail'):
            value = value.strip('<>')
        elif fieldname in ('previous'):
            sha, filename = value.split(' ', 1)
            value = {'commit': sha, 'file': filename}
        return fieldname, value

    def get_blame(self, filename, revision=None):
        data = self.git_lines(['blame', '--porcelain', revision if revision else None, '--', filename])

        commits = {}
        lines = []

        current_commit = None
        for item in data:
            headermatch = self.HEADER_RE.match(item)
            if headermatch:
                sha = headermatch.group('sha')
                commits.setdefault(sha, {})['sha'] = sha
                current_commit = sha
            elif item[0] == '\t':
                lines.append((current_commit, item[1:]))
            else:
                field, val = self.parse_commit_line(item)
                commits.setdefault(current_commit, {})[field] = val

        return commits, lines

    def get_commit_date(self, commit):
        return datetime.fromtimestamp(commit.get('committer-time'))

    def format_blame(self, commits, lines):
        content = []
        template = u"{sha} {file}({author} {date}) {line}"

        files = set(c.get('filename') for _, c in commits.items() if c.get('filename'))
        max_file = max(len(f) for f in files)
        max_name = max(len(c.get('committer', '')) for _, c in commits.items())

        for sha, line in lines:
            commit = commits.get(sha)
            date = self.get_commit_date(commit)
            c = template.format(
                sha=sha[:8],
                file=commit.get('filename').ljust(max_file + 1) if len(files) > 1 else '',
                author=commit.get('committer', '').ljust(max_name + 1, ' '),
                date=date.strftime("%a %b %H:%M:%S %Y"),
                line=line
            )
            content.append(c)
        return "\n".join(content)

    def is_visible(self):
        return False

    def run(self, edit, filename=None, revision=None):
        filename = filename or self.view.settings().get('git_blame_file')
        revision = revision or self.view.settings().get('git_blame_rev')

        commits, lines = self.get_blame(filename, revision)
        blame = self.format_blame(commits, lines)

        if blame:
            self.view.set_read_only(False)
            if self.view.size() > 0:
                self.view.erase(edit, sublime.Region(0, self.view.size()))
            self.view.insert(edit, 0, blame)
            self.view.set_read_only(True)


class GitBlameShowCommand(TextCommand):

    def is_visible(self):
        return False

    def run(self, edit):
        lines = [self.view.lines(s) for s in self.view.sel()]
        commits = set()
        for lineset in lines:
            for line in lineset:
                commit, _ = self.view.substr(line).split(' ', 1)
                if commit != '00000000':
                    commits.add(commit)

        if len(commits) == 0:
            sublime.error_message('No commits selected.')
            return

        if len(commits) > 5:
            if not sublime.ok_cancel_dialog('This will open %s tabs. Are you sure you want to continue?' % len(commits), 'Open tabs'):
                return

        window = self.view.window()
        for c in commits:
            window.run_command('git_show', {'obj': c})


class GitBlameBlameCommand(TextCommand):

    def is_visible(self):
        return False

    def run(self, edit):
        lines = [self.view.lines(s) for s in self.view.sel()]
        commits = set()
        for lineset in lines:
            for line in lineset:
                l, _ = self.view.substr(line).split('(', 1)
                commit, filename = l.split(' ', 1)
                commits.add((commit, filename.strip() if filename.strip() else self.view.settings().get('git_blame_file')))

        window = self.view.window()
        for c, f in commits:
            window.run_command('git_blame', {'filename': f, 'revision': c})
