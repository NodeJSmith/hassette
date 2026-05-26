"""Tests for shell completion generation — verifies zsh function naming is correct."""

import re

from hassette.cli import generate_completion, normalize_zsh_completion

# Trimmed from real cyclopts 4.16.1 output — single inlined function, no
# separate per-subcommand helpers.
ZSH_CYCLOPTS_416 = """\
#compdef hassette

_cyclopts_hassette() {
  local line state

  _arguments -C \\
    '--help[Display this message and exit.]' \\
    '1: :->cmds' \\
    '*::arg:->args'

  case $state in
    cmds)
      local -a commands
      commands=(
        'status:Show system status.'
      )
      _describe -t commands 'command' commands
      ;;
    args)
      case $words[1] in
        status)
          _arguments \\
            '--help[Display this message and exit.]'
          ;;
      esac
      ;;
  esac
}
"""

ZSH_ALREADY_CLEAN = """\
#compdef hassette

_hassette() {
  local line state

  _arguments -C \\
    '--help[Display this message and exit.]'
}
"""

ZSH_HYPHENATED_PROG = """\
#compdef my-app

_cyclopts_my-app() {
  local line state
}
"""


class TestNormalizeZshCompletion:
    def test_strips_cyclopts_prefix_from_function(self):
        result = normalize_zsh_completion(ZSH_CYCLOPTS_416, "hassette")
        assert "_cyclopts_hassette" not in result
        assert "_hassette()" in result

    def test_noop_when_no_prefix(self):
        result = normalize_zsh_completion(ZSH_ALREADY_CLEAN, "hassette")
        assert result == ZSH_ALREADY_CLEAN

    def test_hyphenated_prog_name(self):
        result = normalize_zsh_completion(ZSH_HYPHENATED_PROG, "my-app")
        assert "_my-app()" in result
        assert "_cyclopts_" not in result


class TestGenerateCompletionNormalization:
    """Tests with monkeypatched cyclopts output to verify normalization logic."""

    def test_zsh_normalizes_cyclopts_prefix(self, capsys, monkeypatch):
        monkeypatch.setattr("cyclopts.core.App.generate_completion", lambda _self, **_kw: ZSH_CYCLOPTS_416)
        generate_completion(shell="zsh")  # noqa: S604
        output = capsys.readouterr().out
        assert "_cyclopts_hassette" not in output
        assert re.search(r"_hassette\(\)", output)

    def test_zsh_passthrough_when_already_clean(self, capsys, monkeypatch):
        monkeypatch.setattr("cyclopts.core.App.generate_completion", lambda _self, **_kw: ZSH_ALREADY_CLEAN)
        generate_completion(shell="zsh")  # noqa: S604
        output = capsys.readouterr().out
        assert "_hassette()" in output


class TestGenerateCompletionRealOutput:
    """Tests against real cyclopts output — guards against any version's prefix."""

    def test_bash_output_not_modified(self, capsys):
        generate_completion(shell="bash")  # noqa: S604
        output = capsys.readouterr().out
        assert "_cyclopts_" not in output

    def test_fish_output_not_modified(self, capsys):
        generate_completion(shell="fish")  # noqa: S604
        output = capsys.readouterr().out
        assert "_cyclopts_" not in output

    def test_zsh_has_no_cyclopts_prefix(self, capsys):
        generate_completion(shell="zsh")  # noqa: S604
        output = capsys.readouterr().out
        cyclopts_funcs = re.findall(r"_cyclopts_\w+", output)
        assert cyclopts_funcs == [], f"Found un-normalized cyclopts functions: {cyclopts_funcs}"
