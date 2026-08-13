export interface Cell {
  tokens_in: number;
  tokens_out: number;
  tokens_cached: number;
}

export interface TokenStatsResponse {
  novels: Array<{
    novel_id: string;
    title: string;
    subsystems: Record<string, { by_chapter: Record<string, Cell>; total: Cell }>;
    total: Cell;
  }>;
  grand_total: Cell;
}

export interface SubsystemRow {
  name: string;
  total: Cell;
  chapters: Array<{ key: string } & Cell>;
}

export interface NovelRow {
  novelId: string;
  title: string;
  total: Cell;
  subsystems: SubsystemRow[];
}

export interface DashboardModel {
  grandTotal: Cell;
  novels: NovelRow[];
}

export function toDashboardModel(resp: TokenStatsResponse): DashboardModel {
  return {
    grandTotal: resp.grand_total,
    novels: resp.novels.map((n) => ({
      novelId: n.novel_id,
      title: n.title,
      total: n.total,
      subsystems: Object.entries(n.subsystems).map(([name, s]) => ({
        name,
        total: s.total,
        chapters: Object.entries(s.by_chapter)
          .map(([key, c]) => ({ key, ...c }))
          .sort((a, b) => a.key.localeCompare(b.key)),
      })),
    })),
  };
}

export function filterNovelsByTitle(novels: NovelRow[], query: string): NovelRow[] {
  const q = query.trim().toLowerCase();
  if (!q) return novels;
  return novels.filter((n) => n.title.toLowerCase().includes(q));
}
