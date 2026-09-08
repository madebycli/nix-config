#[path = "../../../vendor/linutil-tui/src/confirmation.rs"]
mod confirmation;
#[path = "../../../vendor/linutil-tui/src/float.rs"]
mod float;
#[path = "../../../vendor/linutil-tui/src/hint.rs"]
mod hint;
mod running_command;
mod state;
#[path = "../../../vendor/linutil-tui/src/system_info.rs"]
mod system_info;
#[path = "../../../vendor/linutil-tui/src/theme.rs"]
mod theme;

use clap::Parser;
use ratatui::{
    backend::CrosstermBackend,
    crossterm::{
        event::{self, DisableMouseCapture, EnableMouseCapture, Event, KeyEventKind},
        style::ResetColor,
        terminal::{disable_raw_mode, enable_raw_mode, EnterAlternateScreen, LeaveAlternateScreen},
        ExecutableCommand,
    },
    Terminal,
};
use running_command::TERMINAL_UPDATED;
use state::AppState;
use std::{
    io::{stdout, Result, Stdout},
    sync::atomic::Ordering,
    time::Duration,
};
use theme::Theme;

#[derive(Debug, Parser, Clone)]
#[command(
    name = "nix-settings",
    version,
    about = "NixOS configuration and system manager"
)]
struct Args {
    #[arg(short, long, value_enum, default_value_t = Theme::Default)]
    theme: Theme,
    #[arg(short = 'm', long)]
    mouse: bool,
    #[arg(short = 's', long)]
    size_bypass: bool,
}

fn main() -> Result<()> {
    let args = Args::parse();
    stdout().execute(EnterAlternateScreen)?;
    if args.mouse {
        stdout().execute(EnableMouseCapture)?;
    }
    let mut state = AppState::new(args.theme, args.mouse, args.size_bypass);
    enable_raw_mode()?;
    let mut terminal = Terminal::new(CrosstermBackend::new(stdout()))?;
    terminal.clear()?;
    let result = run(&mut terminal, &mut state);
    disable_raw_mode()?;
    terminal.backend_mut().execute(LeaveAlternateScreen)?;
    if args.mouse {
        terminal.backend_mut().execute(DisableMouseCapture)?;
    }
    terminal.backend_mut().execute(ResetColor)?;
    terminal.show_cursor()?;
    result
}

fn run(terminal: &mut Terminal<CrosstermBackend<Stdout>>, state: &mut AppState) -> Result<()> {
    loop {
        if !event::poll(Duration::from_millis(30))? {
            if TERMINAL_UPDATED
                .compare_exchange(true, false, Ordering::AcqRel, Ordering::Acquire)
                .is_ok()
            {
                terminal.draw(|frame| state.draw(frame))?;
            }
            continue;
        }
        match event::read()? {
            Event::Key(key) => {
                if key.kind != KeyEventKind::Press && key.kind != KeyEventKind::Repeat {
                    continue;
                }
                if !state.handle_key(&key) {
                    return Ok(());
                }
            }
            Event::Mouse(mouse) if !state.handle_mouse(&mouse) => return Ok(()),
            _ => {}
        }
        terminal.draw(|frame| state.draw(frame))?;
    }
}
