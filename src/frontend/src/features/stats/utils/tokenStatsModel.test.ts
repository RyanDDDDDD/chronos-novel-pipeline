import { describe, expect, it } from "vitest";
import { filterNovelsByTitle, toDashboardModel, type TokenStatsResponse } from "./tokenStatsModel";

const resp: TokenStatsResponse = {
  novels: [{
    novel_id: "default", title: "默认",
    subsystems: {
      author_loop: { by_chapter: { "6": { tokens_in: 100, tokens_out: 40, tokens_cached: 0 } },
                     total: { tokens_in: 100, tokens_out: 40, tokens_cached: 0 } },
    },
    total: { tokens_in: 100, tokens_out: 40, tokens_cached: 0 },
  }],
  grand_total: { tokens_in: 100, tokens_out: 40, tokens_cached: 0 },
};

describe("toDashboardModel", () => {
  it("展开小说×子系统×章行", () => {
    const m = toDashboardModel(resp);
    expect(m.novels[0].subsystems[0].name).toBe("author_loop");
    expect(m.novels[0].subsystems[0].chapters[0].key).toBe("6");
    expect(m.grandTotal.tokens_in).toBe(100);
  });
});

describe("filterNovelsByTitle", () => {
  it("空查询返回全部", () => {
    const novels = toDashboardModel(resp).novels;
    expect(filterNovelsByTitle(novels, "")).toEqual(novels);
    expect(filterNovelsByTitle(novels, "   ")).toEqual(novels);
  });

  it("按标题关键词过滤（忽略大小写）", () => {
    const novels = toDashboardModel({
      ...resp,
      novels: [
        resp.novels[0],
        { ...resp.novels[0], novel_id: "other", title: "另一部小说" },
        { ...resp.novels[0], novel_id: "en", title: "Another Novel" },
      ],
    }).novels;
    expect(filterNovelsByTitle(novels, "另一").map((n) => n.title)).toEqual(["另一部小说"]);
    expect(filterNovelsByTitle(novels, "NOVEL").map((n) => n.title)).toEqual(["Another Novel"]);
  });
});
