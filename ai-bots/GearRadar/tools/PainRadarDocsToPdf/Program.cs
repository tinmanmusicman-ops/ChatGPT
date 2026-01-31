using Markdig;
using Markdig.Syntax;
using Markdig.Syntax.Inlines;
using QuestPDF.Fluent;
using QuestPDF.Helpers;
using QuestPDF.Infrastructure;

QuestPDF.Settings.License = LicenseType.Community;

var input = GetArg(args, "-i", "--input") ?? "";
var output = GetArg(args, "-o", "--output") ?? "";

if (string.IsNullOrWhiteSpace(input) || string.IsNullOrWhiteSpace(output))
{
    Console.Error.WriteLine("Usage: dotnet run -- -i <input.md> -o <output.pdf>");
    return 2;
}

if (!File.Exists(input))
{
    Console.Error.WriteLine($"Input not found: {input}");
    return 2;
}

var markdown = await File.ReadAllTextAsync(input);
var pipeline = new MarkdownPipelineBuilder()
    .UseAdvancedExtensions()
    .Build();

var doc = Markdown.Parse(markdown, pipeline);

Document.Create(container =>
{
    container.Page(page =>
    {
        page.Size(PageSizes.Letter);
        page.Margin(36);
        page.DefaultTextStyle(t => t.FontFamily("Segoe UI").FontSize(11).FontColor("#111827"));

        page.Content().Column(col =>
        {
            col.Spacing(6);
            RenderBlocks(col, doc);
        });

        page.Footer().AlignCenter().Text(t =>
        {
            t.Span("PainRadar — How It Works").FontSize(9).FontColor("#6B7280");
        });
    });
}).GeneratePdf(output);

Console.WriteLine($"Wrote PDF: {output}");
return 0;

static string? GetArg(string[] args, params string[] names)
{
    for (var i = 0; i < args.Length; i++)
    {
        if (!names.Contains(args[i], StringComparer.OrdinalIgnoreCase))
            continue;
        if (i + 1 >= args.Length)
            return null;
        return args[i + 1];
    }
    return null;
}

static void RenderBlocks(ColumnDescriptor col, MarkdownDocument document)
{
    foreach (var block in document)
    {
        switch (block)
        {
            case HeadingBlock hb:
                RenderHeading(col, hb);
                break;
            case ParagraphBlock pb:
                RenderParagraph(col, pb);
                break;
            case ListBlock lb:
                RenderList(col, lb);
                break;
            case FencedCodeBlock fcb:
                RenderCodeBlock(col, fcb);
                break;
            case CodeBlock cb:
                RenderCodeBlock(col, cb);
                break;
            case QuoteBlock qb:
                RenderQuote(col, qb);
                break;
            case ThematicBreakBlock:
                col.Item().PaddingVertical(6).LineHorizontal(1).LineColor("#E5E7EB");
                break;
            default:
                if (block is ContainerBlock container)
                    RenderContainer(col, container);
                break;
        }
    }
}

static void RenderContainer(ColumnDescriptor col, ContainerBlock container)
{
    foreach (var child in container)
    {
        if (child is ParagraphBlock pb)
            RenderParagraph(col, pb);
        else if (child is ListBlock lb)
            RenderList(col, lb);
        else if (child is FencedCodeBlock fcb)
            RenderCodeBlock(col, fcb);
        else if (child is CodeBlock cb)
            RenderCodeBlock(col, cb);
        else if (child is HeadingBlock hb)
            RenderHeading(col, hb);
        else if (child is QuoteBlock qb)
            RenderQuote(col, qb);
        else if (child is ThematicBreakBlock)
            col.Item().PaddingVertical(6).LineHorizontal(1).LineColor("#E5E7EB");
    }
}

static void RenderHeading(ColumnDescriptor col, HeadingBlock hb)
{
    var text = InlineToPlainText(hb.Inline);
    var size = hb.Level switch
    {
        1 => 22,
        2 => 16,
        3 => 13,
        _ => 12
    };

    col.Item().PaddingTop(hb.Level == 1 ? 0 : 10).Text(t =>
    {
        t.Span(text).FontSize(size).SemiBold();
    });
}

static void RenderParagraph(ColumnDescriptor col, ParagraphBlock pb)
{
    if (pb.Inline is null)
        return;

    col.Item().Text(t =>
    {
        RenderInline(t, pb.Inline);
    });
}

static void RenderList(ColumnDescriptor col, ListBlock lb)
{
    foreach (var item in lb)
    {
        if (item is not ListItemBlock lib)
            continue;

        col.Item().Row(r =>
        {
            r.Spacing(6);
            r.ConstantItem(14).AlignTop().Text(lb.IsOrdered ? $"{GetListIndex(lib)}." : "•").SemiBold();
            r.RelativeItem().Column(c =>
            {
                c.Spacing(4);
                RenderContainer(c, lib);
            });
        });
    }
}

static int GetListIndex(ListItemBlock item)
{
    var parent = item.Parent as ListBlock;
    if (parent is null)
        return 1;
    var idx = 1;
    foreach (var child in parent)
    {
        if (ReferenceEquals(child, item))
            return idx;
        idx++;
    }
    return 1;
}

static void RenderQuote(ColumnDescriptor col, QuoteBlock qb)
{
    col.Item().BorderLeft(3).BorderColor("#CBD5E1").PaddingLeft(10).Column(c =>
    {
        c.Spacing(4);
        RenderContainer(c, qb);
    });
}

static void RenderCodeBlock(ColumnDescriptor col, LeafBlock code)
{
    var text = code.Lines.ToString() ?? "";
    col.Item()
        .Background("#F3F4F6")
        .Border(1)
        .BorderColor("#E5E7EB")
        .Padding(10)
        .Text(t =>
        {
            t.DefaultTextStyle(s => s.FontFamily("Consolas").FontSize(10));
            t.Span(text);
        });
}

static string InlineToPlainText(ContainerInline? inline)
{
    if (inline is null)
        return "";

    var parts = new List<string>();
    foreach (var child in inline)
    {
        switch (child)
        {
            case LiteralInline lit:
                parts.Add(lit.Content.ToString());
                break;
            case LineBreakInline:
                parts.Add("\n");
                break;
            case CodeInline ci:
                parts.Add(ci.Content);
                break;
            case EmphasisInline em:
                parts.Add(InlineToPlainText(em));
                break;
            case LinkInline li:
                parts.Add(InlineToPlainText(li));
                break;
        }
    }
    return string.Concat(parts).Trim();
}

static void RenderInline(TextDescriptor t, ContainerInline inline)
{
    foreach (var child in inline)
    {
        switch (child)
        {
            case LiteralInline lit:
                t.Span(lit.Content.ToString());
                break;
            case LineBreakInline:
                t.Span("\n");
                break;
            case EmphasisInline em:
                RenderEmphasis(t, em);
                break;
            case CodeInline ci:
                t.Span(ci.Content).FontFamily("Consolas").FontSize(10).FontColor("#111827").BackgroundColor("#F3F4F6");
                break;
            case LinkInline li:
                RenderLink(t, li);
                break;
        }
    }
}

static void RenderEmphasis(TextDescriptor t, EmphasisInline em)
{
    var content = InlineToPlainText(em);
    if (em.DelimiterCount >= 2)
        t.Span(content).SemiBold();
    else
        t.Span(content).Italic();
}

static void RenderLink(TextDescriptor t, LinkInline li)
{
    var label = InlineToPlainText(li);
    if (!string.IsNullOrWhiteSpace(li.Url))
        t.Span(label).FontColor("#1D4ED8").Underline();
    else
        t.Span(label);

    if (!string.IsNullOrWhiteSpace(li.Url))
        t.Span($" ({li.Url})").FontColor("#6B7280").FontSize(9);
}
