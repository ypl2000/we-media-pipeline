// 按 HyperFrames 内部同款分词（Intl.Segmenter "ja"）切旁白成字幕词组。
//
// 用法: node caption_groups.js < input.json
//   stdin:  {"text": "...", "maxChars": 14}
//   stdout: {"words": [{w, start, end}], "groups": [{words, start, end, t}]}
//
// 为什么用 node: Python 没有 Intl.Segmenter, 而 HyperFrames 的 craft 规则
// (0.5s + 0.3s/词) 就是按这个分词算的, 自己近似一定会算错。
//
// 规则（对齐 HyperFrames captions.md）:
//   - 在句号/问号/叹号处断句, 逗号顿号处也断
//   - 中文按字符数断（Intl.Segmenter 把中文切成 1~2 字一个词, 按词数断会断得很碎）
//   - 字幕文字不带标点（标点只用来断句, 不进画面）
const WORD_RUNS = /[\p{L}\p{M}\p{N}%$]+(?:['’][\p{L}\p{M}\p{N}]+)*/gu;
const SEGMENTER = new Intl.Segmenter("ja", { granularity: "word" });
const SENTENCE_END = /[。！？!?…]/;
const SOFT_BREAK = /[，、：:；;,.!]/;

function segmentWords(text) {
  const words = [];
  WORD_RUNS.lastIndex = 0;
  let m;
  while ((m = WORD_RUNS.exec(text)) !== null) {
    const run = m[0];
    const runStart = m.index;
    let offset = 0;
    for (const seg of SEGMENTER.segment(run)) {
      if (!seg.isWordLike) continue;
      words.push({
        w: seg.segment,
        start: runStart + offset,
        end: runStart + offset + seg.segment.length,
      });
      offset += seg.segment.length;
    }
  }
  return words;
}

// 词与词之间的空隙里有标点 → 那是断句点
function gapBreak(text, words, i) {
  if (i + 1 >= words.length) return "end";
  const gap = text.slice(words[i].end, words[i + 1].start);
  if (SENTENCE_END.test(gap)) return "sentence";
  if (SOFT_BREAK.test(gap)) return "soft";
  return null;
}

function groupWords(text, words, maxChars) {
  const groups = [];
  let cur = [];
  let curStart = -1;
  let curEnd = -1;
  // brk 记录这组是被什么断开的: sentence/soft(标点) 或 chars(超字数)。
  // Python 侧 fit_cues 合并字幕时靠它禁止跨句号拼接。
  const flush = (brk) => {
    if (cur.length) {
      // 取原文片段（保留中文不加空格、英文词间空格），去掉标点
      const t = text.slice(curStart, curEnd).replace(/[，。？！、；：,.;?!：—…～~"'（）()《》【】]/g, "").trim();
      groups.push({ words: cur, start: curStart, end: curEnd, t, brk: brk || "chars" });
    }
    cur = [];
    curStart = -1;
    curEnd = -1;
  };
  for (let i = 0; i < words.length; i++) {
    const w = words[i];
    cur.push(i);
    if (curStart < 0) curStart = w.start;
    curEnd = w.end;
    const brk = gapBreak(text, words, i);
    const len = curEnd - curStart;
    // 标点处断句；字符数超了也断（中文按字符断，英文单词长所以 maxChars 要够大）
    if (brk || len >= maxChars) {
      flush(brk);
    }
  }
  flush();
  return groups;
}

let raw = "";
process.stdin.setEncoding("utf8");
process.stdin.on("data", (d) => (raw += d));
process.stdin.on("end", () => {
  const input = JSON.parse(raw);
  const text = input.text;
  const words = segmentWords(text);
  const groups = groupWords(text, words, input.maxChars ?? 14);
  console.log(JSON.stringify({ words, groups }));
});
