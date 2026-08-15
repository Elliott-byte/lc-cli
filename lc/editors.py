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
"   <leader>p   show/hide the problem statement in a left split
"   <leader>o   open the problem page in your browser (for figures/animations)
"   <leader>m   save this problem to the lc review deck (spaced repetition)
"   <leader>q   write everything, then quit Vim (back to the lc TUI/shell)
" The statement pane shows `lc show` fully rendered in a terminal split when
" the editor supports it, the raw README.md otherwise; `let
" g:lc_statement_render = 0` forces the plain file. The pane opens
" automatically when the solution file is the only window; `let
" g:lc_auto_statement = 0` turns that off. Inside the pane, q closes it.
" Quitting the solution (:q, ZZ, …) never strands you in the pane: a
" statement pane left as the last window takes Vim down with it.
" The leader key is backslash unless changed.

if exists('g:loaded_lc_cli')
  finish
endif
let g:loaded_lc_cli = 1

function! s:LcReadme() abort
  return expand('%:p:h') . '/README.md'
endfunction

function! s:LcSlug() abort
  let l:meta_path = expand('%:p:h') . '/.lc.json'
  if !filereadable(l:meta_path)
    return ''
  endif
  return get(json_decode(join(readfile(l:meta_path), '')), 'slug', '')
endfunction

function! s:LcStatementWin() abort
  " The window showing this problem's statement pane, or -1.
  let l:dir = expand('%:p:h')
  for l:w in range(1, winnr('$'))
    if getbufvar(winbufnr(l:w), 'lc_statement_for', '') ==# l:dir
      return l:w
    endif
  endfor
  return -1
endfunction

function! s:LcOpenStatement() abort
  let l:dir = expand('%:p:h')
  let l:slug = s:LcSlug()
  let l:width = min([60, &columns / 2])
  " `lc show` in a terminal split renders the statement properly — colors,
  " example boxes, real superscripts. The raw README.md is the fallback for
  " editors without terminal support (or g:lc_statement_render = 0).
  if get(g:, 'lc_statement_render', 1) && l:slug !=# '' && executable('lc')
        \ && (has('terminal') || has('nvim'))
    " Size the window first so `lc show` renders at its final width.
    topleft vertical new
    execute 'vertical resize ' . l:width
    if has('nvim')
      call termopen('lc show ' . shellescape(l:slug))
    else
      execute 'terminal ++curwin ++norestore lc show ' . l:slug
    endif
  else
    if !filereadable(s:LcReadme())
      return
    endif
    execute 'topleft vertical split ' . fnameescape(s:LcReadme())
    setlocal readonly nomodifiable wrap linebreak
    execute 'vertical resize ' . l:width
  endif
  let b:lc_statement_for = l:dir
  setlocal winfixwidth nonumber norelativenumber
  nnoremap <buffer> q :call <SID>LcCloseStatement()<CR>
  wincmd p
endfunction

function! s:LcUnsaved() abort
  " Modified buffers holding a real file — the only ones worth protecting.
  " A terminal or scratch buffer has nothing to save and must never stop us.
  return filter(getbufinfo({'bufmodified': 1}),
        \ 'getbufvar(v:val.bufnr, "&buftype") ==# "" && !empty(v:val.name)')
endfunction

function! s:LcCloseStatement() abort
  " The pane runs `lc show` in a terminal: its job blocks plain :close and
  " :quit with E948, and there is nothing in it to save — so force it. On
  " the last window :close would be E444 anyway; leaving Vim is what closing
  " the last thing on screen means. Real unsaved work still gets a veto.
  if winnr('$') == 1 && tabpagenr('$') == 1
    if empty(s:LcUnsaved())
      quit!
    else
      quit
    endif
  else
    close!
  endif
endfunction

function! s:LcQuitAll() abort
  " Write every modified file, then go. `:xall` cannot do this: it tries to
  " write the statement terminal too and dies on E382/E948 without quitting.
  let l:here = bufnr('%')
  let l:failed = []
  for l:info in s:LcUnsaved()
    try
      execute 'buffer' l:info.bufnr
      write
    catch
      call add(l:failed, fnamemodify(l:info.name, ':t'))
    endtry
  endfor
  if !empty(l:failed)
    execute 'buffer' l:here
    echohl ErrorMsg
    echo 'lc: could not write ' . join(l:failed, ', ') . ' — staying put'
    echohl None
    return
  endif
  " Everything real is on disk; the ! is only for the statement terminal.
  qall!
endfunction

function! s:LcOpenWeb() abort
  let l:slug = s:LcSlug()
  if l:slug !=# ''
    " Inside WSL the browser is on the Windows side; wslview/explorer.exe
    " reach it where xdg-open does not exist.
    let l:opener = has('mac') ? 'open'
        \ : has('wsl') ? (executable('wslview') ? 'wslview' : 'explorer.exe')
        \ : 'xdg-open'
    call system(l:opener . ' ' . shellescape('https://leetcode.com/problems/' . l:slug . '/'))
  endif
endfunction

function! s:LcReview() abort
  " `lc review add` with no argument reads .lc.json from the working
  " directory, so this works wherever Vim was started from. Runs without a
  " shell prompt: it is one line of output, not a judge run.
  let l:out = system('cd ' . shellescape(expand('%:p:h')) . ' && lc review add')
  echo substitute(substitute(l:out, '\n\+$', '', ''), '\n', ' ', 'g')
endfunction

function! s:LcToggleStatement() abort
  let l:win = s:LcStatementWin()
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
  " LeetCode's Python starters indent with spaces, and one stray real Tab is
  " a TabError from the judge. Keep Python solution buffers space-only, and
  " retab on save so pasted tabs (which bypass expandtab) get converted too.
  " `let g:lc_python_indent = 0` turns both off.
  if get(g:, 'lc_python_indent', 1)
        \ && (&filetype ==# 'python' || expand('%:e') ==# 'py')
    setlocal expandtab shiftwidth=4 softtabstop=4
    augroup lc_cli_py
      autocmd! * <buffer>
      autocmd BufWritePre <buffer>
            \ if search('\t', 'nw') | silent keepjumps retab | endif
    augroup END
  endif
  " shellescape() so a workspace path with spaces survives the shell.
  nnoremap <buffer> <leader>t :w<CR>:execute '!cd ' . shellescape(expand('%:p:h')) . ' && lc test'<CR>
  nnoremap <buffer> <leader>s :w<CR>:execute '!cd ' . shellescape(expand('%:p:h')) . ' && lc submit'<CR>
  nnoremap <buffer> <leader>p :call <SID>LcToggleStatement()<CR>
  nnoremap <buffer> <leader>o :call <SID>LcOpenWeb()<CR>
  " Mid-solve: "I'll want to see this one again."
  nnoremap <buffer> <leader>m :call <SID>LcReview()<CR>
  " One stroke back to whatever launched Vim (the lc TUI resumes on exit).
  nnoremap <buffer> <leader>q :call <SID>LcQuitAll()<CR>
  " Fresh `lc pick` / `lc edit`: put the statement alongside the solution.
  if get(g:, 'lc_auto_statement', 1) && winnr('$') == 1
        \ && expand('%:t') !=# 'README.md'
    call s:LcOpenStatement()
  endif
endfunction

augroup lc_cli
  autocmd!
  autocmd BufReadPost,BufNewFile * call s:LcSetup()
  " :q in the solution closes only that window, dropping the user into the
  " statement pane with no obvious way on. A pane left as the last window
  " means everything else was quit — follow along. (Plain :quit, so a hidden
  " modified buffer still stops Vim rather than being discarded.)
  autocmd BufEnter * if winnr('$') == 1 && tabpagenr('$') == 1
        \ && exists('b:lc_statement_for') | call s:LcCloseStatement() | endif
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
