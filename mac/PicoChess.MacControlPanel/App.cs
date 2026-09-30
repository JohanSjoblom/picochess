using Avalonia;
using Avalonia.Controls.ApplicationLifetimes;
using Avalonia.Themes.Fluent;

namespace PicoChess.MacControlPanel;

internal sealed class App : Application
{
    public override void Initialize()
    {
        Name = "PicoChess";
        Styles.Add(new FluentTheme());
    }

    public override void OnFrameworkInitializationCompleted()
    {
        if (ApplicationLifetime is IClassicDesktopStyleApplicationLifetime desktop)
        {
            var window = new MainWindow(desktop.Args ?? []);
            desktop.MainWindow = window;
            // Cmd+Q goes through the same "stop PicoChess first?" prompt as closing the window.
            desktop.ShutdownRequested += (_, e) =>
            {
                if (window.IsPicoChessRunning)
                {
                    e.Cancel = true;
                    window.Close();
                }
            };
        }
        base.OnFrameworkInitializationCompleted();
    }
}
