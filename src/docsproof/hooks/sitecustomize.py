"""Loaded when Python starts inside the sandbox (its folder is on PYTHONPATH), before the program runs.

It stops a documented command right after the program has read its command line, so nothing the command
would do is ever done, and it records what the program's own parser said about the command line:
- "accepted": the parser took every word (the program is stopped here, with exit code 0)
- "unknown_option" or "unknown_command": the parser named a word it doesn't know
- "usage_error": any other complaint from the parser, with its message

It covers the three command-line libraries the measured projects use: argparse, optparse, and click (with
the libraries built on it, such as typer and rich-click). Events are written, one JSON object per line, to
the file named by DOCSPROOF_EVENTS. Only the first process reads that variable; it and PYTHONPATH are
removed, so programs the command starts record nothing.
"""
import json
import os
import sys

_EVENTS = os.environ.pop("DOCSPROOF_EVENTS", None)
os.environ.pop("PYTHONPATH", None)


def _record(kind, message="", **extra):
    with open(_EVENTS, "a", encoding="utf-8") as out:
        out.write(json.dumps({"kind": kind, "message": str(message)[:500], **extra}) + "\n")


def _accepted():
    _record("accepted")
    sys.stdout.flush()
    sys.stderr.flush()
    os._exit(0)


def _patch_argparse():
    import argparse

    depth = [0]
    extras_seen = [[]]
    parse_known_args = argparse.ArgumentParser.parse_known_args
    check_value = argparse.ArgumentParser._check_value
    error = argparse.ArgumentParser.error

    def remainder(parser, namespace):
        # words kept for a second parser (twine's "args"), so the command line isn't fully read yet
        return any(action.nargs == argparse.REMAINDER and getattr(namespace, action.dest, None)
                   for action in parser._actions)

    def patched_parse_known_args(self, args=None, namespace=None, *rest, **kwargs):
        depth[0] += 1
        try:
            namespace, extras = parse_known_args(self, args, namespace, *rest, **kwargs)
        finally:
            depth[0] -= 1
        if depth[0] == 0:  # the program's own call, not a subcommand's parser inside it
            extras_seen[0] = list(extras)
            if not extras and not remainder(self, namespace):
                _accepted()
        return namespace, extras

    def patched_check_value(self, action, value):
        try:
            return check_value(self, action, value)
        except argparse.ArgumentError:
            if isinstance(action, argparse._SubParsersAction):
                _record("unknown_command", value, command=value)
            raise

    def patched_error(self, message):
        # Unknown words are recorded only here, when the parser refuses them: a program that reads its
        # command line with parse_known_args may keep them on purpose.
        if message.startswith("unrecognized arguments"):
            for word in extras_seen[0]:
                if word.startswith("-") and word != "-":
                    _record("unknown_option", word, option=word.split("=", 1)[0])
        _record("usage_error", message)
        return error(self, message)

    argparse.ArgumentParser.parse_known_args = patched_parse_known_args
    argparse.ArgumentParser._check_value = patched_check_value
    argparse.ArgumentParser.error = patched_error


def _patch_optparse():
    import optparse

    match_long_opt = optparse.OptionParser._match_long_opt
    process_short_opts = optparse.OptionParser._process_short_opts
    parse_args = optparse.OptionParser.parse_args

    def patched_match_long_opt(self, opt):
        try:
            return match_long_opt(self, opt)
        except (optparse.BadOptionError, optparse.AmbiguousOptionError) as err:
            kind = "unknown_option" if isinstance(err, optparse.BadOptionError) else "usage_error"
            _record(kind, str(err), option=opt)
            raise

    def patched_process_short_opts(self, rargs, values):
        try:
            return process_short_opts(self, rargs, values)
        except optparse.BadOptionError as err:
            _record("unknown_option", str(err), option=err.opt_str)
            raise

    def patched_parse_args(self, args=None, values=None):
        # Programs such as coverage and yt-dlp replace error() and may not exit, so an unknown option is
        # recorded where optparse finds it (above), and the command line is accepted only if this returns.
        result = parse_args(self, args, values)
        _accepted()
        return result

    optparse.OptionParser._match_long_opt = patched_match_long_opt
    optparse.OptionParser._process_short_opts = patched_process_short_opts
    optparse.OptionParser.parse_args = patched_parse_args


def _patch_click():
    try:
        import click
    except ImportError:
        return
    from click import exceptions

    owner = next(cls for cls in click.Command.__mro__ if "main" in vars(cls))
    main = owner.main
    make_context = click.Command.make_context
    resolve_command = click.Group.resolve_command

    def refusal(err):
        # Recorded where an error leaves the parser. Click also raises errors it catches itself (a group
        # that passes unknown options on to its default command), and those aren't refusals.
        if isinstance(err, exceptions.NoSuchOption):
            _record("unknown_option", err.option_name, option=err.option_name)
        _record("usage_error", err.format_message())

    def patched_main(self, *args, **kwargs):
        try:
            main(self, *args, **kwargs)
        except SystemExit as exit_:
            if exit_.code not in (0, None):
                raise
        _accepted()

    def patched_make_context(self, *args, **kwargs):
        try:
            return make_context(self, *args, **kwargs)
        except exceptions.UsageError as err:
            refusal(err)
            raise

    def patched_invoke(ctx, callback, /, *args, **kwargs):
        return None  # the command's own code never runs

    def patched_resolve_command(self, ctx, args):
        try:
            return resolve_command(self, ctx, args)
        except exceptions.NoSuchOption as err:
            refusal(err)
            raise
        except exceptions.UsageError as err:
            if args:
                _record("unknown_command", args[0], command=args[0])
            refusal(err)
            raise

    owner.main = patched_main
    click.Command.make_context = patched_make_context
    click.Context.invoke = patched_invoke
    click.Group.resolve_command = patched_resolve_command


if _EVENTS:
    _patch_argparse()
    _patch_optparse()
    _patch_click()
