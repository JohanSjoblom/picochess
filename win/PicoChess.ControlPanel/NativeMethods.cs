using System.Runtime.InteropServices;

namespace PicoChess.ControlPanel;

internal static partial class NativeMethods
{
    public const uint CtrlCEvent = 0;
    private const uint Th32csSnapProcess = 0x00000002;
    private static readonly IntPtr InvalidHandleValue = new(-1);

    [LibraryImport("kernel32.dll", SetLastError = true)]
    [return: MarshalAs(UnmanagedType.Bool)]
    public static partial bool AttachConsole(uint processId);

    [LibraryImport("kernel32.dll", SetLastError = true)]
    [return: MarshalAs(UnmanagedType.Bool)]
    public static partial bool FreeConsole();

    [LibraryImport("kernel32.dll", SetLastError = true)]
    [return: MarshalAs(UnmanagedType.Bool)]
    public static partial bool SetConsoleCtrlHandler(IntPtr handlerRoutine, [MarshalAs(UnmanagedType.Bool)] bool add);

    [LibraryImport("kernel32.dll", SetLastError = true)]
    [return: MarshalAs(UnmanagedType.Bool)]
    public static partial bool GenerateConsoleCtrlEvent(uint ctrlEvent, uint processGroupId);

    [LibraryImport("kernel32.dll", SetLastError = true)]
    private static partial IntPtr CreateToolhelp32Snapshot(uint flags, uint processId);

    [LibraryImport("kernel32.dll", EntryPoint = "Process32FirstW", SetLastError = true)]
    [return: MarshalAs(UnmanagedType.Bool)]
    private static partial bool Process32First(IntPtr snapshot, ref ProcessEntry32 entry);

    [LibraryImport("kernel32.dll", EntryPoint = "Process32NextW", SetLastError = true)]
    [return: MarshalAs(UnmanagedType.Bool)]
    private static partial bool Process32Next(IntPtr snapshot, ref ProcessEntry32 entry);

    [LibraryImport("kernel32.dll", SetLastError = true)]
    [return: MarshalAs(UnmanagedType.Bool)]
    private static partial bool CloseHandle(IntPtr handle);

    /// <summary>Returns the process ids of all descendants of <paramref name="rootProcessId"/>.</summary>
    public static IReadOnlyList<int> GetDescendantProcessIds(int rootProcessId)
    {
        var parents = new Dictionary<int, List<int>>();
        var snapshot = CreateToolhelp32Snapshot(Th32csSnapProcess, 0);
        if (snapshot == InvalidHandleValue) return [];

        try
        {
            var entry = new ProcessEntry32 { Size = (uint)Marshal.SizeOf<ProcessEntry32>() };
            for (var ok = Process32First(snapshot, ref entry); ok; ok = Process32Next(snapshot, ref entry))
            {
                var parent = (int)entry.ParentProcessId;
                if (!parents.TryGetValue(parent, out var children))
                {
                    parents[parent] = children = [];
                }
                children.Add((int)entry.ProcessId);
            }
        }
        finally
        {
            CloseHandle(snapshot);
        }

        var result = new List<int>();
        var pending = new Queue<int>([rootProcessId]);
        while (pending.Count > 0)
        {
            if (!parents.TryGetValue(pending.Dequeue(), out var children)) continue;
            foreach (var child in children.Where(child => child != rootProcessId && !result.Contains(child)))
            {
                result.Add(child);
                pending.Enqueue(child);
            }
        }
        return result;
    }

    [StructLayout(LayoutKind.Sequential)]
    private unsafe struct ProcessEntry32
    {
        public uint Size;
        public uint Usage;
        public uint ProcessId;
        public IntPtr DefaultHeapId;
        public uint ModuleId;
        public uint Threads;
        public uint ParentProcessId;
        public int PriorityClassBase;
        public uint Flags;
        public fixed char ExeFile[260];
    }
}
