//! Restore terminal state on ordinary errors as well as successful exit.
use ratatui::crossterm::{
    cursor::Show,
    event::{DisableMouseCapture, EnableMouseCapture},
    style::ResetColor,
    terminal::{disable_raw_mode, enable_raw_mode, EnterAlternateScreen, LeaveAlternateScreen},
    ExecutableCommand,
};
use std::io::{stdout, Result};

#[derive(Default)]
pub struct TerminalGuard {
    alternate: bool,
    mouse: bool,
    raw: bool,
}

impl TerminalGuard {
    pub fn enter(mouse: bool) -> Result<Self> {
        let mut guard = Self::default();
        stdout().execute(EnterAlternateScreen)?;
        guard.alternate = true;
        if mouse {
            stdout().execute(EnableMouseCapture)?;
            guard.mouse = true;
        }
        enable_raw_mode()?;
        guard.raw = true;
        Ok(guard)
    }
}

impl Drop for TerminalGuard {
    fn drop(&mut self) {
        if self.raw {
            let _ = disable_raw_mode();
        }
        if self.mouse {
            let _ = stdout().execute(DisableMouseCapture);
        }
        if self.alternate {
            let _ = stdout().execute(LeaveAlternateScreen);
        }
        let _ = stdout().execute(ResetColor);
        let _ = stdout().execute(Show);
    }
}
