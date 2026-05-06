"""Demo application showing the Textual TUI integration."""

from textual.app import App, ComposeResult
from textual.containers import Vertical, Horizontal
from textual.widgets import Static, Header, Footer, Input, TextArea, OptionList, Markdown


class PilotDemo(App):
    """Demo application for pilot TUI."""
    
    CSS = """
    Screen {
        layout: vertical;
    }
    
    #header {
        height: 3;
        background: $primary;
        color: $text;
        content-align: center middle;
    }
    
    #content {
        height: 1fr;
        overflow-y: auto;
    }
    
    #footer {
        height: 3;
        background: $secondary;
        color: $text;
    }
    
    .input-area {
        height: 5;
        border: solid $primary;
    }
    
    .output-area {
        height: 1fr;
        border: solid $secondary;
    }
    """
    
    def compose(self) -> ComposeResult:
        yield Header()
        yield Vertical(
            Static("Pilot Demo - AI Coding Agent", id="header"),
            Vertical(
                Input(placeholder="Type your message...", id="user_input"),
                TextArea(id="output_area", read_only=True),
                id="content",
            ),
            Static("Press Ctrl+C to exit", id="footer"),
        )
        yield Footer()
    
    def on_mount(self) -> None:
        """Called when app is mounted."""
        output_area = self.query_one("#output_area", TextArea)
        output_area.text = "Welcome to Pilot!\nType a message below and press Enter."
    
    def on_input_submitted(self, event: Input.Submitted) -> None:
        """Handle input submission."""
        if event.input.id == "user_input":
            message = event.input.value
            if message:
                output_area = self.query_one("#output_area", TextArea)
                output_area.text += f"\n> {message}"
                output_area.text += f"\n  [Response to: {message}]"
                event.input.value = ""


if __name__ == "__main__":
    app = PilotDemo()
    app.run()
