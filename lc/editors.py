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
"   space       start the solve clock (opening a problem only arms it)
"   <leader>z   pause the solve clock behind a cover (space there resumes)
"   <leader>Z   reset the solve clock to 00:00 (asks first)
" Quitting Vim pauses a running clock; space resumes it on the next visit.
"   <leader>q   write everything, then quit Vim (back to the lc TUI/shell)
" The statement pane shows `lc show` fully rendered in a terminal split when
" the editor supports it, the raw README.md otherwise; `let
" g:lc_statement_render = 0` forces the plain file. The pane opens
" automatically when the solution file is the only window; `let
" g:lc_auto_statement = 0` turns that off. The pane is read-only and the
" cursor starts in the solution — CTRL-W h goes over to read, q closes the
" pane, and the keys above work there too, though its statusline shows only
" `q close` — the full list sits beside it on the solution's statusline.
" Double-clicking the pane's url
" line opens the problem page: Vim owns the mouse there, so the terminal
" never sees the click, and Vim's terminal drops the hyperlink escape anyway.
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

function! s:LcDir() abort
  " The problem directory for whatever window you are in — the statement
  " pane remembers it, so the keys work there too instead of doing nothing.
  return get(b:, 'lc_statement_for', expand('%:p:h'))
endfunction

function! s:LcSlug(...) abort
  let l:dir = a:0 ? a:1 : s:LcDir()
  let l:meta_path = l:dir . '/.lc.json'
  if !filereadable(l:meta_path)
    return ''
  endif
  return get(json_decode(join(readfile(l:meta_path), '')), 'slug', '')
endfunction

function! s:LcSolutionWin(dir) abort
  " The window holding a real file from this problem — where a judge run
  " has to happen, since that is the buffer to write. The statement pane is
  " a real file too when it falls back to README.md, so skip it by its mark:
  " otherwise the pane counts as its own solution and \t writes the README.
  for l:w in range(1, winnr('$'))
    let l:b = winbufnr(l:w)
    if getbufvar(l:b, '&buftype') ==# '' && bufname(l:b) !=# ''
          \ && getbufvar(l:b, 'lc_statement_for', '') ==# ''
          \ && fnamemodify(bufname(l:b), ':p:h') ==# a:dir
      return l:w
    endif
  endfor
  return -1
endfunction

function! s:LcJudge(action) abort
  " Save and run `lc test` / `lc submit`. Pressing this in the statement
  " pane hops to the solution first rather than silently doing nothing.
  let l:dir = s:LcDir()
  let l:win = s:LcSolutionWin(l:dir)
  if l:win != -1
    execute l:win . 'wincmd w'
  endif
  if &buftype ==# ''
    write
  endif
  execute '!cd ' . shellescape(l:dir) . ' && lc ' . a:action
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

function! s:LcFocusSolution(dir) abort
  " By name rather than by "previous window": window order is not ours to
  " assume, and `wincmd p` is only a guess about how we got here.
  let l:back = s:LcSolutionWin(a:dir)
  if l:back != -1
    execute l:back . 'wincmd w'
  elseif &buftype !=# ''
    wincmd p
  endif
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
      execute 'silent! file' fnameescape('[statement] ' . l:slug)
    else
      " Started hidden and then shown, never with ++curwin: a terminal opened
      " into the current window seizes the cursor in Terminal-Job mode when
      " Vim returns to its main loop, undoing any wincmd we do here — you land
      " in the statement typing at `lc show`. A buffer displayed after the
      " fact grabs nothing, so the cursor stays where we put it.
      " term_name because Vim otherwise names the buffer after the command it
      " ran, and the pane would read "!lc show two-sum [finished]" — which
      " looks like something went wrong. term_kill so the job cannot veto
      " :q / :qa with E948; older Vim without it still works, it just
      " complains on quit.
      " A list, not a string: term_start() splits a string into arguments
      " itself and never involves a shell, so shellescape() would hand `lc`
      " a slug with the quotes still on it — "no problem matching
      " "'two-sum'"". A list is passed through untouched, spaces and all.
      let l:cmd = ['lc', 'show', l:slug]
      let l:opts = {'hidden': 1, 'norestore': 1, 'curwin': 0,
            \ 'term_name': '[statement] ' . l:slug, 'term_kill': 'term'}
      try
        let l:buf = term_start(l:cmd, l:opts)
      catch /E475\|E118/
        call remove(l:opts, 'term_kill')
        let l:buf = term_start(l:cmd, l:opts)
      endtry
      execute 'keepalt buffer' l:buf
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
  " :wall and :wqa try to write every modified buffer, and a terminal cannot
  " be written (E382) — which aborts the whole command. There is nothing to
  " save in here, so let the write succeed and do nothing.
  augroup lc_cli_pane
    autocmd! * <buffer>
    autocmd BufWriteCmd <buffer> setlocal nomodified
  augroup END
  " The pane is something to read: 'nomodifiable' comes with the terminal
  " buffer, and the README fallback sets it above. (Forcing Terminal-Normal
  " mode early would make it read-only sooner, but Vim stops drawing job
  " output into a buffer in that mode — you would get a blank statement.
  " `lc show` prints and exits, and Vim leaves job mode when it does.)
  " The same keys as the solution buffer: landing in the pane and pressing
  " \t used to do nothing at all, with no hint why.
  nnoremap <buffer> q :call <SID>LcCloseStatement()<CR>
  nnoremap <buffer> <leader>t :call <SID>LcJudge('test')<CR>
  nnoremap <buffer> <leader>s :call <SID>LcJudge('submit')<CR>
  nnoremap <buffer> <leader>p :call <SID>LcCloseStatement()<CR>
  nnoremap <buffer> <leader>o :call <SID>LcOpenWeb()<CR>
  nnoremap <buffer> <leader>m :call <SID>LcReview()<CR>
  nnoremap <buffer> <expr> <Space> <SID>LcSpaceKey()
  nnoremap <buffer> <leader>z :call <SID>LcTimerToggle()<CR>
  nnoremap <buffer> <leader>Z :call <SID>LcTimerReset()<CR>
  nnoremap <buffer> <leader>q :call <SID>LcQuitAll()<CR>
  nnoremap <buffer> <2-LeftMouse> <LeftMouse>:call <SID>LcClickOpen()<CR>
  " Only the pane's own key. The full list sits an inch away on the
  " solution's statusline — and those keys all work from here regardless.
  call s:LcKeyHints([['', 'q close']])
  " Back to the code — that is what you are here to type in.
  call s:LcFocusSolution(l:dir)
  " Once more after startup finishes: Vim re-enters the first window when it
  " is done opening files, which is the pane, and for a terminal pane that
  " means Terminal-Job mode with `lc show` eating your keys. A zero timer
  " runs after that and before you can type, so the cursor ends up here.
  if !v:vim_did_enter
    call timer_start(0, {-> s:LcFocusSolution(l:dir)})
  endif
endfunction

function! s:LcClockText() abort
  " One clock, on the solution's statusline only: in a vertical split both
  " statuslines share a screen row, and the same time twice an inch apart
  " reads as a rendering bug.
  if exists('b:lc_statement_for')
    return ''
  endif
  " The lc solve clock, read from $LC_HOME/timer.json — written by the TUI
  " and `lc pick`, stopped by an accepted `lc submit` (\s included). Vim is
  " where the solving happens, so this is where the clock has to be visible.
  let l:home = empty($LC_HOME) ? expand('~/.lc') : $LC_HOME
  try
    let l:t = json_decode(join(readfile(l:home . '/timer.json'), ''))
  catch
    return ''
  endtry
  if type(l:t) != v:t_dict || get(l:t, 'slug', '') !=# s:LcSlug()
    return ''
  endif
  " Plain text, no emoji: the clock symbols are double-width emoji to the
  " terminal but single-width to Vim, and the disagreement tears the
  " statusline highlight apart around them.
  let l:sec = float2nr(get(l:t, 'accum', 0.0))
  let l:mark = 'paused '
  if get(l:t, 'done')
    let l:mark = 'done '
  elseif get(l:t, 'started') isnot v:null
    let l:sec += max([0, float2nr(localtime() - get(l:t, 'started'))])
    let l:mark = ''
  elseif get(l:t, 'accum', 0.0) == 0.0
    " Armed, never started: opening a problem readies the clock, space
    " starts it — deliberately, not as a side effect of walking in.
    return 'space starts the clock'
  endif
  return l:mark . s:LcFmtClock(l:sec)
endfunction

function! s:LcTick(...) abort
  " Never while `lc test`'s output, a prompt or the cmdline owns the screen:
  " r is the hit-enter prompt (and \Z's confirm), c the cmdline, ! a running
  " shell command. A statusline repainted onto that screen splatters clock
  " digits over the judge's report.
  if mode(1) !~# '^[rc!]'
    silent! redrawstatus!
  endif
endfunction

function! s:LcHintText() abort
  " As many hints as the window can show, most useful first — a status line
  " that overflows just loses its right-hand end silently.
  let l:lead = get(g:, 'mapleader', '\')
  let l:parts = map(copy(get(b:, 'lc_hints', [])),
        \ 'v:val[0] ==# "" ? v:val[1] : l:lead . v:val[0] . " " . v:val[1]')
  let l:clock = s:LcClockText()
  if l:clock !=# ''
    call insert(l:parts, l:clock)
  endif
  let l:room = winwidth(0) - 16
  while len(l:parts) > 1 && strwidth(join(l:parts, '  ')) > l:room
    call remove(l:parts, -1)
  endwhile
  return join(l:parts, '  ')
endfunction

function! s:LcKeyHints(keys) abort
  " The keys, on the window's own status line — Vim has no footer, and a
  " message echoed once is gone by the time you want it. `let
  " g:lc_statusline = 0` leaves your own status line alone.
  if !get(g:, 'lc_statusline', 1)
    return
  endif
  let b:lc_hints = a:keys
  " %< truncates the name first, so the keys survive a narrow window.
  let &l:statusline = '%<%f %m%= %{' . expand('<SID>') . 'LcHintText()} '
  " A status line only redraws on events, and a clock that moves once per
  " cursor motion is not a clock. One shared ticker, started lazily.
  if !exists('s:lc_ticker') && has('timers')
    let s:lc_ticker = timer_start(1000, function('s:LcTick'), {'repeat': -1})
  endif
  if &laststatus < 2
    set laststatus=2
  endif
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
    call s:LcTimerAutoPause()   " closing the last window is leaving Vim
    if empty(s:LcUnsaved())
      quit!
    else
      quit
    endif
  else
    close!
  endif
endfunction

function! s:LcPaneQuit() abort
  " :q with the cursor in the statement pane means "I am done", not "dismiss
  " this accessory" — closing only the pane leaves you one more :q away from
  " where you were going, and on a running `lc show` it fails outright with
  " E948. q and \p still close the pane and keep you in Vim.
  " Anything unsaved vetoes it: then :q behaves like plain Vim.
  if !empty(s:LcUnsaved())
    return          " something real is unsaved: let :q behave like plain Vim
  endif
  if exists('b:lc_statement_for')
    " Commands run inside an autocmd fire no further autocmds, so the
    " VimLeavePre hook never sees these exits — pause the clock by hand.
    call s:LcTimerAutoPause()
    qall!           " :q from the pane means leave
    return
  endif
  " ...and so does :q from the solution when the pane is the only thing left
  " beside it — nobody quits the code to sit in the statement. Splits you
  " opened yourself are none of our business, so require exactly the two.
  if winnr('$') == 2 && tabpagenr('$') == 1 && s:LcStatementWin() != -1
    call s:LcTimerAutoPause()
    qall!
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
  call s:LcTimerAutoPause()
  qall!
endfunction

function! s:LcTimerFile() abort
  let l:home = empty($LC_HOME) ? expand('~/.lc') : $LC_HOME
  try
    let l:t = json_decode(join(readfile(l:home . '/timer.json'), ''))
  catch
    return {}
  endtry
  return type(l:t) == v:t_dict ? l:t : {}
endfunction

function! s:LcFmtClock(sec) abort
  let l:h = a:sec / 3600
  if l:h > 0
    return printf('%d:%02d:%02d', l:h, (a:sec % 3600) / 60, a:sec % 60)
  endif
  return printf('%02d:%02d', a:sec / 60, a:sec % 60)
endfunction

function! s:LcTimerToggle() abort
  " \z — pause behind a cover, like the TUI's space. The cover is a fresh
  " tab page: it hides the statement and the code both, and closing it
  " restores the exact window layout underneath.
  let l:t = s:LcTimerFile()
  if empty(l:t) || get(l:t, 'slug', '') !=# s:LcSlug() || get(l:t, 'done')
    echo 'lc: no clock running here'
    return
  endif
  if get(l:t, 'started') is v:null
    " \z is the pause button, nothing else. It used to start a stopped
    " clock — a toggle — which read as "pause is broken": you pressed
    " pause, and the meter began to run.
    echo 'lc: clock is not running — space starts it'
    return
  endif
  call system('lc timer pause')
  let l:sec = float2nr(get(s:LcTimerFile(), 'accum', 0.0))
  tab new
  setlocal buftype=nofile bufhidden=wipe nobuflisted noswapfile
  setlocal nonumber norelativenumber statusline=\ 
  let l:pad = repeat([''], max([1, winheight(0) / 2 - 2]))
  let l:mid = repeat(' ', max([0, (winwidth(0) - 12) / 2]))
  call setline(1, l:pad + [l:mid . 'paused at ' . s:LcFmtClock(l:sec), '',
        \ l:mid . 'space resumes'])
  setlocal nomodifiable
  nnoremap <buffer> <Space> :call <SID>LcBreakResume()<CR>
  nnoremap <buffer> <CR> :call <SID>LcBreakResume()<CR>
  nnoremap <buffer> q :call <SID>LcBreakResume()<CR>
  nnoremap <buffer> <leader>z :call <SID>LcBreakResume()<CR>
  silent! file [break]
endfunction

" The problems this Vim session actually edited — so quitting some other,
" unrelated Vim cannot pause a solve running elsewhere.
let s:lc_slugs = {}

function! s:LcTimerAutoPause() abort
  " Leaving the editor is leaving the solve: the clock must not keep
  " charging for time spent back in the TUI or the shell. Space (or \z)
  " picks it back up on the next visit. Written directly rather than via
  " `lc timer pause` — a python spawn on every quit would make :q lag.
  let l:t = s:LcTimerFile()
  if empty(l:t) || get(l:t, 'started') is v:null || get(l:t, 'done')
        \ || !has_key(s:lc_slugs, get(l:t, 'slug', ''))
    return
  endif
  let l:t.accum = get(l:t, 'accum', 0.0)
        \ + max([0, localtime() - float2nr(get(l:t, 'started'))])
  let l:t.started = v:null
  let l:home = empty($LC_HOME) ? expand('~/.lc') : $LC_HOME
  call writefile([json_encode(l:t)], l:home . '/timer.json')
endfunction

function! s:LcSpaceKey() abort
  " Space starts (or resumes) this problem's clock when it is standing
  " still — including when there is no clock yet, so a bare `vim
  " solution.py` works the same as coming in through lc. Once this
  " problem's clock is running (or clocked out), space is vim's own.
  let l:t = s:LcTimerFile()
  let l:mine = !empty(l:t) && get(l:t, 'slug', '') ==# s:LcSlug()
  if l:mine && (get(l:t, 'started') isnot v:null || get(l:t, 'done'))
    return ' '
  endif
  " expand('<SID>'), not \<SID>: the returned keys are replayed as typed,
  " where a literal <SID> is just eight characters of nothing.
  return ':call ' . expand('<SID>') . "LcTimerStart()\<CR>"
endfunction

function! s:LcTimerStart() abort
  call system('lc timer start ' . shellescape(s:LcSlug()))
  redrawstatus!
  echo 'lc: clock started'
endfunction

function! s:LcTimerReset() abort
  " \Z — back to 00:00 and running: a fresh attempt at this problem. One
  " shifted slip away from \z, and it erases the elapsed time, so it asks.
  let l:t = s:LcTimerFile()
  if empty(l:t) || get(l:t, 'slug', '') !=# s:LcSlug()
    echo 'lc: no clock running here'
    return
  endif
  if confirm('Reset the solve clock to 00:00?', "&Yes\n&No", 2) != 1
    " Enter takes the default (No): say so, or declining reads as broken.
    echo 'lc: not reset'
    return
  endif
  call system('lc timer reset')
  redrawstatus!
  echo 'lc: clock reset'
endfunction

function! s:LcBreakResume() abort
  " Closing the cover is the resume, exactly as in the TUI.
  call system('lc timer resume')
  tabclose
  redrawstatus!
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
  let l:out = system('cd ' . shellescape(s:LcDir()) . ' && lc review add')
  echo substitute(substitute(l:out, '\n\+$', '', ''), '\n', ' ', 'g')
endfunction

function! s:LcClickOpen() abort
  " Vim owns the mouse in the pane (defaults.vim sets mouse=a), so a click on
  " the URL never reaches the terminal — and Vim's terminal drops the escape
  " that would make it a hyperlink anyway. Double-clicking the line that
  " carries the URL is the gesture people try; make it the one that works.
  if getline('.') =~# 'leetcode\.com/problems/'
    call s:LcOpenWeb()
  endif
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
  nnoremap <buffer> <leader>t :call <SID>LcJudge('test')<CR>
  nnoremap <buffer> <leader>s :call <SID>LcJudge('submit')<CR>
  nnoremap <buffer> <leader>p :call <SID>LcToggleStatement()<CR>
  nnoremap <buffer> <leader>o :call <SID>LcOpenWeb()<CR>
  " Mid-solve: "I'll want to see this one again."
  nnoremap <buffer> <leader>m :call <SID>LcReview()<CR>
  let s:lc_slugs[s:LcSlug(expand('%:p:h'))] = 1
  " Space starts the armed clock; once it runs, space is space again.
  nnoremap <buffer> <expr> <Space> <SID>LcSpaceKey()
  " Pause the solve clock behind a cover; \z again (or space there) resumes.
  nnoremap <buffer> <leader>z :call <SID>LcTimerToggle()<CR>
  nnoremap <buffer> <leader>Z :call <SID>LcTimerReset()<CR>
  " One stroke back to whatever launched Vim (the lc TUI resumes on exit).
  nnoremap <buffer> <leader>q :call <SID>LcQuitAll()<CR>
  call s:LcKeyHints([['t', 'test'], ['s', 'submit'], ['z', 'pause'],
        \ ['q', 'quit'], ['p', 'statement'], ['m', 'deck'], ['o', 'web'],
        \ ['Z', 'reset']])
  " Fresh `lc pick` / `lc edit`: put the statement alongside the solution.
  if get(g:, 'lc_auto_statement', 1) && winnr('$') == 1
        \ && expand('%:t') !=# 'README.md'
    call s:LcOpenStatement()
  endif
endfunction

augroup lc_cli
  autocmd!
  autocmd BufReadPost,BufNewFile * call s:LcSetup()
  " QuitPre fires before :q decides which window to close, which is where the
  " statement pane gets to say "that means leave".
  autocmd QuitPre * call s:LcPaneQuit()
  " Quitting Vim pauses this session's running clock — editor time is the
  " solve time, and the TUI has no clock to warn that one is still burning.
  autocmd VimLeavePre * call s:LcTimerAutoPause()
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
