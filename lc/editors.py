"""Editor integrations installed by `lc setup`.

Vim support is a single plugin file dropped into ``~/.vim/plugin`` — Vim loads
that directory automatically, so there are no ``.vimrc`` edits and deleting the
file uninstalls it.
"""

from __future__ import annotations

from pathlib import Path

#: Written verbatim to `vim_plugin_path()` by `lc setup vim`.
VIM_PLUGIN = r'''" lc.vim — Vim integration for the lc LeetCode CLI.
" Installed by `lc setup vim`; delete this file to uninstall.
"
" In a buffer whose directory contains .lc.json (an `lc pick` workspace):
"   <leader>t   write the file, then run `lc test`
"   <leader>s   write the file, then run `lc submit`
"   <leader>p   show/hide the problem statement (README.md) in a left split
" The statement pane opens automatically when the solution file is the only
" window; `let g:lc_auto_statement = 0` in your vimrc turns that off. Inside
" the pane, q also closes it. The leader key is backslash unless changed.

if exists('g:loaded_lc_cli')
  finish
endif
let g:loaded_lc_cli = 1

function! s:LcReadme() abort
  return expand('%:p:h') . '/README.md'
endfunction

function! s:LcOpenStatement() abort
  let l:readme = s:LcReadme()
  if !filereadable(l:readme)
    return
  endif
  execute 'topleft vertical split ' . fnameescape(l:readme)
  setlocal readonly nomodifiable wrap linebreak nonumber norelativenumber
  setlocal winfixwidth
  nnoremap <buffer> q :close<CR>
  execute 'vertical resize ' . min([60, &columns / 2])
  wincmd p
endfunction

function! s:LcToggleStatement() abort
  let l:win = bufwinnr(bufnr(s:LcReadme()))
  if l:win != -1 && winnr('$') > 1
    execute l:win . 'close'
  else
    call s:LcOpenStatement()
  endif
endfunction

function! s:LcSetup() abort
  if !filereadable(expand('%:p:h') . '/.lc.json')
    return
  endif
  " shellescape() so a workspace path with spaces survives the shell.
  nnoremap <buffer> <leader>t :w<CR>:execute '!cd ' . shellescape(expand('%:p:h')) . ' && lc test'<CR>
  nnoremap <buffer> <leader>s :w<CR>:execute '!cd ' . shellescape(expand('%:p:h')) . ' && lc submit'<CR>
  nnoremap <buffer> <leader>p :call <SID>LcToggleStatement()<CR>
  " Fresh `lc pick` / `lc edit`: put the statement alongside the solution.
  if get(g:, 'lc_auto_statement', 1) && winnr('$') == 1
        \ && expand('%:t') !=# 'README.md'
    call s:LcOpenStatement()
  endif
endfunction

augroup lc_cli
  autocmd!
  autocmd BufReadPost,BufNewFile * call s:LcSetup()
augroup END
'''


def vim_plugin_path() -> Path:
    return Path.home() / ".vim" / "plugin" / "lc.vim"


def install_vim_plugin(force: bool = False) -> tuple[Path, str]:
    """Write the plugin and say what happened: installed, updated or unchanged.

    A file whose content differs — a local edit, or a plugin from another lc
    version — is only replaced when ``force`` is set; otherwise this raises
    FileExistsError so the caller can suggest ``--force``.
    """
    path = vim_plugin_path()
    if path.exists():
        if path.read_text() == VIM_PLUGIN:
            return path, "unchanged"
        if not force:
            raise FileExistsError(str(path))
        path.write_text(VIM_PLUGIN)
        return path, "updated"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(VIM_PLUGIN)
    return path, "installed"
