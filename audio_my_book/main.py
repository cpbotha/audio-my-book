import asyncio
import fnmatch
import os
import re
from pathlib import Path

import click
import openai
from chunkipy import TextChunker

client = openai.AsyncOpenAI(api_key=os.environ.get("OPENAI_API_KEY"))
text_chunker = TextChunker(4096)

# pandoc "/Users/charlbotha/Library/CloudStorage/OneDrive-Personal/03-Resources/books/calibre/Moore, Geoffrey A_/Crossing the Chasm, 3rd Edition_ Marketing and Selling Disruptive Products to Mainstream Custome (41)/Crossing the Chasm, 3rd Edition_ Marketing - Moore, Geoffrey A_.epub" -t plain -o chasm.txt
# then went through and prepended "# " to all the chapter headings


def slugify(chapter_title):
    return re.sub(r"[^a-zA-Z0-9]", "_", chapter_title)


async def _process_chunk(chunk, speech_filename, max_retries=10, retry_delay=5):
    click.echo(f"Processing chunk: {speech_filename.name}")
    speech_filename.with_suffix(".txt").write_text(chunk)
    # handle openai.RateLimitError
    retries = 0
    success = False
    while not success and retries < max_retries:
        try:
            response = await client.audio.speech.create(model="tts-1", voice="fable", input=chunk)
            await response.astream_to_file(speech_filename)
            click.echo(f"✅ Completed chunk: {speech_filename.name}")
            success = True
        except openai.RateLimitError:
            retries += 1
            click.echo(f"Rate limit exceeded for {speech_filename.name}. Retrying in {retry_delay} seconds...")
            await asyncio.sleep(retry_delay)  # Wait for a bit before retrying

    if not success:
        click.echo(
            f"❌ failed to convert {speech_filename.name}. Allowing rest of batch to continue. Re-run later to fill in blanks."
        )


async def _process_chapter(chapter_text, chapter_title, output_dir):
    click.echo("Processing chapter: " + chapter_title)
    tasks = []
    async with asyncio.TaskGroup() as tg:
        for i, chunk in enumerate(text_chunker.chunk(chapter_text)):
            # zero pad i to 3 digits
            speech_filename = output_dir / f"{slugify(chapter_title)}---{i:0>3}.mp3"
            if speech_filename.exists():
                click.echo(f"Skipping {speech_filename} as it already exists")
            else:
                tasks.append(tg.create_task(_process_chunk(chunk, speech_filename)))

    click.echo(f"📘 Completed tasks for chapter {chapter_title}: {[task.result for task in tasks]}")


async def _process_book(input_txt):
    input_path = Path(input_txt)
    with input_path.open() as f:
        text = f.read()
        chapters = []

        # scan through the whole text, storing chapter locations and names
        for match in re.finditer(r"#\s+(.*)", text):
            chapters.append((match.start(), match.group(1)))

        # check each of the chapters against user-supplied fnmatch specs
        selected_chapters = []
        for idx, chapter in enumerate(chapters):
            # later expand this check to a list of user-supplied fnmatch specs
            if fnmatch.fnmatch(chapter[1], "Chapter *"):
                # start, end, title
                # if it's the last chapter, the final index is of course -1
                selected_chapters.append((chapter[0], chapters[idx + 1][0] if idx < len(chapters) else -1, chapter[1]))

        # process each chapter, chapters and chunks all in parallel
        chap_results = [None] * len(selected_chapters)
        async with asyncio.TaskGroup() as tg:
            for chap_idx, chapter in enumerate(selected_chapters):
                chapter_text = text[chapter[0] : chapter[1]]
                chap_results[chap_idx] = tg.create_task(_process_chapter(chapter_text, chapter[2], input_path.parent))

        print(chap_results)


@click.command()
@click.argument(
    "input_txt",
    type=click.Path(
        exists=True,
        readable=True,
        path_type=Path,
    ),
)
def cli(input_txt):
    loop = asyncio.get_event_loop()
    loop.run_until_complete(_process_book(input_txt))


if __name__ == "__main__":
    cli()
