// Some desktops, such as Wayland compositors, can refuse a clipboard write
// from a window without focus and report nothing; a copy counts only when
// the clipboard reads the same text back.
const lines = (text) => text.replace(/\r\n/g, "\n");

function copyText(clipboard, text) {
  clipboard.writeText(text);
  const copied = clipboard.readText();
  if (typeof copied !== "string" || lines(copied) !== lines(text))
    throw new Error(
      "The clipboard did not accept the text. Click the DazedTL window and try again.",
    );
}

module.exports = { copyText };
