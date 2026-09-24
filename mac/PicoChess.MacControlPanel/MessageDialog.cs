using Avalonia;
using Avalonia.Controls;
using Avalonia.Layout;

namespace PicoChess.MacControlPanel;

/// <summary>Minimal modal message box; Avalonia has none built in.</summary>
internal static class MessageDialog
{
    public static Task ShowAsync(Window owner, string title, string message) =>
        ShowCoreAsync(owner, title, message, "OK", cancelText: null);

    public static Task<bool> ConfirmAsync(Window owner, string title, string message, string okText = "OK") =>
        ShowCoreAsync(owner, title, message, okText, "Cancel");

    private static async Task<bool> ShowCoreAsync(Window owner, string title, string message, string okText, string? cancelText)
    {
        var dialog = new Window
        {
            Title = title,
            Width = 440,
            SizeToContent = SizeToContent.Height,
            CanResize = false,
            WindowStartupLocation = WindowStartupLocation.CenterOwner
        };

        var ok = new Button { Content = okText, IsDefault = true, MinWidth = 90 };
        ok.Click += (_, _) => dialog.Close(true);
        var buttons = new StackPanel
        {
            Orientation = Orientation.Horizontal,
            HorizontalAlignment = HorizontalAlignment.Right,
            Spacing = 8
        };
        if (cancelText is not null)
        {
            var cancel = new Button { Content = cancelText, IsCancel = true, MinWidth = 90 };
            cancel.Click += (_, _) => dialog.Close(false);
            buttons.Children.Add(cancel);
        }
        buttons.Children.Add(ok);

        dialog.Content = new StackPanel
        {
            Margin = new Thickness(20),
            Spacing = 16,
            Children =
            {
                new TextBlock { Text = message, TextWrapping = Avalonia.Media.TextWrapping.Wrap },
                buttons
            }
        };

        return await dialog.ShowDialog<bool>(owner);
    }
}
