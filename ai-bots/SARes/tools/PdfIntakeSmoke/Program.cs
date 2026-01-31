if (args.Length is < 1 or > 2)
{
    Console.Error.WriteLine("Usage: PdfIntakeSmoke <path-to-pdf> [path-to-SARes.dll]");
    return 2;
}

var pdfPath = args[0];
var saresDll = args.Length == 2
    ? args[1]
    : Path.GetFullPath(Path.Combine(Environment.CurrentDirectory, "..", "..", "..", "..", "bin", "Release", "net8.0-windows10.0.19041.0", "win-x64", "SARes.dll"));

try
{
    var asm = System.Reflection.Assembly.LoadFrom(saresDll);
    var t = asm.GetType("SARes.engine.PdfResumeImporter", throwOnError: true)!;
    var method = t.GetMethod("ImportPdfToTemplateMarkdown", System.Reflection.BindingFlags.Public | System.Reflection.BindingFlags.Static)!;
    var md = (string)method.Invoke(null, [pdfPath, null])!;

    Console.WriteLine(md.Length <= 2000 ? md : md[..2000]);
    return 0;
}
catch (Exception ex)
{
    var root = ex is System.Reflection.TargetInvocationException tie && tie.InnerException is not null ? tie.InnerException : ex;
    Console.Error.WriteLine("Import failed: " + root.Message);
    Console.Error.WriteLine(root.ToString());
    return 1;
}
