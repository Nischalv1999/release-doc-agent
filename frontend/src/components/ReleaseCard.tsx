"use client";

import { useState } from "react";
import ReactMarkdown from "react-markdown";

interface DocUpdate {
  doc_path: string;
  section: string;
  suggested_content: string;
  action: string;
}

interface CodeInsight {
  filename: string;
  change_type: string;
  observation: string;
  verified: boolean;
}

interface Release {
  id: string;
  name: string;
  status: string;
  created_at: string;
  artifacts: {
    changelog: string;
    internal_release_notes: string;
    customer_release_notes: string;
    documentation_updates: DocUpdate[];
  };
  digest: Record<string, unknown>;
  review: Record<string, unknown>;
  evaluation: {
    hallucination_rate: number;
    ticket_coverage: number;
    doc_recommendation_accuracy: number;
    overall_score: number;
  };
  source_evidence: {
    commits: Array<Record<string, unknown>>;
    pull_requests: Array<Record<string, unknown>>;
    tickets: Array<Record<string, unknown>>;
    relevant_docs: Array<Record<string, unknown>>;
  };
}

interface Props {
  release: Release;
  onApprove: (id: string, edits: Partial<Release["artifacts"]>) => void;
  onBack: () => void;
}

type TabKey = "changelog" | "internal" | "customer" | "docs" | "evidence" | "evaluation";

// --- helpers to safely read GitHub/Jira nested fields ---
function getCommitMessage(c: Record<string, unknown>): string {
  const commitObj = c.commit as Record<string, unknown> | undefined;
  const msg = (commitObj?.message ?? c.message ?? "") as string;
  return msg.split("\n")[0];
}

function getPrNumber(pr: Record<string, unknown>): string | number {
  return (pr.number ?? pr.id ?? "?") as string | number;
}

function getPrAuthor(pr: Record<string, unknown>): string {
  const user = pr.user as Record<string, unknown> | undefined;
  return (user?.login ?? pr.author ?? "unknown") as string;
}

function getPrLabels(pr: Record<string, unknown>): string[] {
  const labels = pr.labels as Array<Record<string, unknown> | string> | undefined;
  if (!labels) return [];
  return labels.map((l) => (typeof l === "string" ? l : (l.name as string) ?? ""));
}

function getTicketFields(t: Record<string, unknown>) {
  const fields = (t.fields as Record<string, unknown>) ?? t;
  const summary = (fields.summary ?? t.summary ?? "No summary") as string;
  const issuetype = (fields.issuetype as Record<string, unknown> | undefined) ?? {};
  const type = (issuetype.name ?? fields.type ?? t.type ?? "?") as string;
  const priorityObj = (fields.priority as Record<string, unknown> | undefined) ?? {};
  const priority = (priorityObj.name ?? fields.priority ?? t.priority ?? "?") as string;
  const statusObj = (fields.status as Record<string, unknown> | undefined) ?? {};
  const status = (statusObj.name ?? fields.status ?? t.status ?? "?") as string;
  return { key: (t.key as string) ?? "?", summary, type, priority, status };
}

export function ReleaseCard({ release, onApprove, onBack }: Props) {
  const [activeTab, setActiveTab] = useState<TabKey>("changelog");
  const [editingTab, setEditingTab] = useState<TabKey | null>(null);
  const [editedChangelog, setEditedChangelog] = useState(release.artifacts.changelog);
  const [editedInternal, setEditedInternal] = useState(release.artifacts.internal_release_notes);
  const [editedCustomer, setEditedCustomer] = useState(release.artifacts.customer_release_notes);
  const [hasEdits, setHasEdits] = useState(false);

  const isApproved = release.status === "approved";
  const needsRevision = release.status === "needs_revision";
  const pendingReview = release.status === "review" || needsRevision;

  const tabs: { key: TabKey; label: string }[] = [
    { key: "changelog", label: "Changelog" },
    { key: "internal", label: "Internal Notes" },
    { key: "customer", label: "Customer Notes" },
    { key: "docs", label: "Doc Updates" },
    { key: "evidence", label: "Source Evidence" },
    { key: "evaluation", label: "AI Evaluation" },
  ];

  const editableTabs: TabKey[] = ["changelog", "internal", "customer"];

  const currentContent = {
    changelog: editedChangelog,
    internal: editedInternal,
    customer: editedCustomer,
  };

  const setContent = {
    changelog: (v: string) => { setEditedChangelog(v); setHasEdits(true); },
    internal: (v: string) => { setEditedInternal(v); setHasEdits(true); },
    customer: (v: string) => { setEditedCustomer(v); setHasEdits(true); },
  };

  const handleApprove = () => {
    onApprove(release.id, {
      changelog: editedChangelog,
      internal_release_notes: editedInternal,
      customer_release_notes: editedCustomer,
    });
    setEditingTab(null);
  };

  const toggleEdit = (tab: TabKey) => {
    setEditingTab(editingTab === tab ? null : tab);
  };

  return (
    <div className="bg-white rounded-lg border shadow-sm">

      {/* ── Header ── */}
      <div className="p-4 border-b flex items-center justify-between">
        <div className="flex items-center gap-3">
          <button onClick={onBack} className="text-gray-500 hover:text-gray-700 text-sm">
            ← Back
          </button>
          <h2 className="text-lg font-semibold">{release.name}</h2>
          <StatusBadge status={release.status} />
        </div>
        <div className="text-xs text-gray-400">
          Generated {new Date(release.created_at).toLocaleString()}
        </div>
      </div>

      {/* ── Human Review Banner ── */}
      {pendingReview && (
        <div
          className={`px-5 py-3 flex items-center justify-between border-b ${
            needsRevision
              ? "bg-orange-50 border-orange-200"
              : "bg-blue-50 border-blue-200"
          }`}
        >
          <div>
            <p
              className={`font-semibold text-sm ${
                needsRevision ? "text-orange-700" : "text-blue-700"
              }`}
            >
              {needsRevision
                ? "⚠️ AI flagged issues — review carefully before approving"
                : "📋 Pending human review"}
            </p>
            <p className="text-xs text-gray-600 mt-0.5">
              Review each tab, edit any content, then click Approve to publish.
            </p>
          </div>
          <button
            onClick={handleApprove}
            className="px-4 py-2 bg-green-600 hover:bg-green-700 text-white text-sm font-medium rounded-md shadow-sm transition"
          >
            {hasEdits ? "Save Edits & Approve" : "Approve Release"}
          </button>
        </div>
      )}

      {/* ── Approved Banner ── */}
      {isApproved && (
        <div className="px-5 py-3 bg-green-50 border-b border-green-200 flex items-center gap-2">
          <span className="text-green-700 font-semibold text-sm">✓ Release approved</span>
          <span className="text-xs text-gray-500">
            · Read-only view
          </span>
        </div>
      )}

      {/* ── Tabs ── */}
      <div className="border-b px-4">
        <nav className="flex gap-1">
          {tabs.map((tab) => (
            <button
              key={tab.key}
              onClick={() => setActiveTab(tab.key)}
              className={`px-3 py-3 text-sm font-medium border-b-2 transition ${
                activeTab === tab.key
                  ? "border-blue-500 text-blue-600"
                  : "border-transparent text-gray-500 hover:text-gray-700"
              }`}
            >
              {tab.label}
              {editingTab === tab.key && (
                <span className="ml-1.5 inline-block w-1.5 h-1.5 rounded-full bg-yellow-400 align-middle" />
              )}
            </button>
          ))}
        </nav>
      </div>

      {/* ── Content ── */}
      <div className="p-6">

        {/* Editable content tabs */}
        {(["changelog", "internal", "customer"] as const).map((key) => {
          const tabMap: Record<string, TabKey> = {
            changelog: "changelog",
            internal: "internal",
            customer: "customer",
          };
          if (activeTab !== tabMap[key]) return null;

          const contentKey = key as keyof typeof currentContent;
          const isEditing = editingTab === tabMap[key];

          return (
            <div key={key}>
              {/* Per-tab edit toolbar — only for non-approved */}
              {!isApproved && (
                <div className="flex items-center justify-between mb-4">
                  <p className="text-xs text-gray-400">
                    {isEditing
                      ? "Editing — changes will be saved when you approve."
                      : "Click Edit to modify this section before approving."}
                  </p>
                  <div className="flex gap-2">
                    {isEditing && (
                      <button
                        onClick={() => setEditingTab(null)}
                        className="px-3 py-1.5 text-sm border rounded-md text-gray-600 hover:bg-gray-50"
                      >
                        Done Editing
                      </button>
                    )}
                    <button
                      onClick={() => toggleEdit(tabMap[key])}
                      className={`px-3 py-1.5 text-sm rounded-md border transition ${
                        isEditing
                          ? "border-yellow-400 bg-yellow-50 text-yellow-700"
                          : "border-gray-300 hover:bg-gray-50 text-gray-600"
                      }`}
                    >
                      {isEditing ? "Editing…" : "✏️ Edit"}
                    </button>
                  </div>
                </div>
              )}

              <MarkdownPanel
                content={currentContent[contentKey]}
                editing={isEditing}
                onChange={setContent[contentKey]}
              />
            </div>
          );
        })}

        {activeTab === "docs" && (
          <DocUpdatesPanel updates={release.artifacts.documentation_updates} />
        )}
        {activeTab === "evidence" && (
          <EvidencePanel evidence={release.source_evidence} digest={release.digest} />
        )}
        {activeTab === "evaluation" && (
          <EvaluationPanel
            evaluation={release.evaluation}
            review={release.review}
            digest={release.digest}
          />
        )}
      </div>

      {/* ── Bottom Approve Bar (persistent when pending) ── */}
      {pendingReview && (
        <div className="px-6 py-4 border-t bg-gray-50 flex items-center justify-between">
          <div className="text-sm text-gray-600">
            {hasEdits ? (
              <span className="text-yellow-700 font-medium">
                ✏️ You have unsaved edits — they will be saved when you approve.
              </span>
            ) : (
              <span>Review all tabs above, then approve when ready.</span>
            )}
          </div>
          <button
            onClick={handleApprove}
            className="px-5 py-2 bg-green-600 hover:bg-green-700 text-white font-medium text-sm rounded-md shadow-sm transition"
          >
            {hasEdits ? "Save Edits & Approve" : "Approve Release"}
          </button>
        </div>
      )}
    </div>
  );
}

/* ─── Sub-components ─────────────────────────────────────────── */

function MarkdownPanel({
  content,
  editing,
  onChange,
}: {
  content: string;
  editing: boolean;
  onChange: (v: string) => void;
}) {
  if (!content) {
    return <p className="text-gray-400 text-sm italic">No content generated.</p>;
  }
  if (editing) {
    return (
      <textarea
        value={content}
        onChange={(e) => onChange(e.target.value)}
        className="w-full h-[28rem] font-mono text-sm p-3 border rounded-md focus:outline-none focus:ring-2 focus:ring-blue-500 resize-y"
        autoFocus
      />
    );
  }
  return (
    <div className="prose prose-sm max-w-none">
      <ReactMarkdown>{content}</ReactMarkdown>
    </div>
  );
}

function DocUpdatesPanel({ updates }: { updates: DocUpdate[] }) {
  if (!updates || updates.length === 0) {
    return <p className="text-gray-500 text-sm">No documentation updates suggested.</p>;
  }
  return (
    <div className="space-y-4">
      {updates.map((u, i) => (
        <div key={i} className="border rounded-lg p-4">
          <div className="flex items-center gap-2 mb-2">
            <span
              className={`px-2 py-0.5 rounded text-xs font-medium ${
                u.action === "add"
                  ? "bg-green-100 text-green-700"
                  : u.action === "update"
                  ? "bg-yellow-100 text-yellow-700"
                  : "bg-blue-100 text-blue-700"
              }`}
            >
              {u.action}
            </span>
            <span className="font-mono text-sm text-gray-700">{u.doc_path}</span>
            {u.section && <span className="text-sm text-gray-500">→ {u.section}</span>}
          </div>
          <div className="bg-gray-50 rounded p-3 text-sm">
            <ReactMarkdown>{u.suggested_content}</ReactMarkdown>
          </div>
        </div>
      ))}
    </div>
  );
}

function EvidencePanel({
  evidence,
  digest,
}: {
  evidence: Release["source_evidence"];
  digest: Record<string, unknown>;
}) {
  return (
    <div className="space-y-8">
      {/* Digest summary */}
      {digest && (
        <section>
          <h3 className="font-semibold text-gray-800 mb-3">AI-Extracted Digest</h3>
          <div className="grid gap-3">
            {(digest.features as string[] | undefined)?.length ? (
              <DigestSection title="Features" items={digest.features as string[]} color="blue" />
            ) : null}
            {(digest.bug_fixes as string[] | undefined)?.length ? (
              <DigestSection title="Bug Fixes" items={digest.bug_fixes as string[]} color="orange" />
            ) : null}
            {(digest.breaking_changes as string[] | undefined)?.length ? (
              <DigestSection
                title="Breaking Changes"
                items={digest.breaking_changes as string[]}
                color="red"
              />
            ) : null}
            {(digest.code_insights as CodeInsight[] | undefined)?.length ? (
              <CodeInsightSection items={digest.code_insights as CodeInsight[]} />
            ) : null}
            <div className="bg-gray-50 rounded p-3 text-sm flex flex-wrap gap-4">
              <span>
                <span className="font-medium">Risk: </span>
                <span
                  className={`font-semibold ${
                    digest.risk_level === "high"
                      ? "text-red-600"
                      : digest.risk_level === "medium"
                      ? "text-yellow-600"
                      : "text-green-600"
                  }`}
                >
                  {String(digest.risk_level ?? "unknown")}
                </span>
              </span>
              {(digest.affected_systems as string[] | undefined)?.length ? (
                <span>
                  <span className="font-medium">Systems: </span>
                  <span className="text-gray-600">
                    {(digest.affected_systems as string[]).join(", ")}
                  </span>
                </span>
              ) : null}
            </div>
          </div>
        </section>
      )}

      {/* Commits */}
      <section>
        <h3 className="font-semibold text-gray-800 mb-3">
          GitHub Commits ({evidence.commits.length})
        </h3>
        <div className="space-y-1.5">
          {evidence.commits.map((c, i) => {
            const sha = String(c.sha ?? "").slice(0, 8);
            const msg = getCommitMessage(c);
            const stats = c.stats as Record<string, number> | undefined;
            const commitObj = c.commit as Record<string, unknown> | undefined;
            const authorObj = commitObj?.author as Record<string, unknown> | undefined;
            const author = String(authorObj?.name ?? "");
            return (
              <div
                key={i}
                className="text-sm font-mono bg-gray-50 rounded px-3 py-2 flex items-center gap-3"
              >
                <span className="text-blue-600 shrink-0">{sha}</span>
                <span className="flex-1 text-gray-800 truncate">{msg}</span>
                {stats && (
                  <span className="text-gray-400 text-xs shrink-0">
                    +{stats.additions} -{stats.deletions}
                  </span>
                )}
                {author && (
                  <span className="text-gray-400 text-xs shrink-0">{author}</span>
                )}
              </div>
            );
          })}
        </div>
      </section>

      {/* Pull Requests */}
      <section>
        <h3 className="font-semibold text-gray-800 mb-3">
          Pull Requests ({evidence.pull_requests.length})
        </h3>
        <div className="space-y-2">
          {evidence.pull_requests.map((pr, i) => {
            const number = getPrNumber(pr);
            const title = String(pr.title ?? "Untitled");
            const author = getPrAuthor(pr);
            const labels = getPrLabels(pr);
            const additions = pr.additions as number | undefined;
            const deletions = pr.deletions as number | undefined;
            const changedFiles = pr.changed_files as number | undefined;
            return (
              <div key={i} className="border rounded-lg p-3">
                <div className="flex items-start justify-between gap-2">
                  <div>
                    <span className="font-mono text-blue-600 font-medium">#{number}</span>
                    <span className="ml-2 font-medium text-gray-800">{title}</span>
                  </div>
                  <span className="text-xs text-gray-500 shrink-0">by {author}</span>
                </div>
                <div className="mt-1.5 flex flex-wrap gap-1.5 items-center">
                  {labels.map((l, li) => (
                    <span
                      key={li}
                      className={`px-1.5 py-0.5 rounded text-xs ${
                        l === "breaking-change" || l === "critical" || l === "security"
                          ? "bg-red-100 text-red-700"
                          : l === "performance"
                          ? "bg-green-100 text-green-700"
                          : "bg-gray-100 text-gray-600"
                      }`}
                    >
                      {l}
                    </span>
                  ))}
                  {additions != null && (
                    <span className="text-xs text-gray-400 ml-auto">
                      +{additions} -{deletions} · {changedFiles} files
                    </span>
                  )}
                </div>
              </div>
            );
          })}
        </div>
      </section>

      {/* Jira Tickets */}
      <section>
        <h3 className="font-semibold text-gray-800 mb-3">
          Jira Tickets ({evidence.tickets.length})
        </h3>
        <div className="space-y-2">
          {evidence.tickets.map((t, i) => {
            const { key, summary, type, priority, status } = getTicketFields(t);
            const fields = (t.fields as Record<string, unknown>) ?? t;
            const storyPoints = (fields.customfield_10016 ?? null) as number | null;
            return (
              <div key={i} className="border rounded-lg p-3">
                <div className="flex items-start justify-between gap-2">
                  <div>
                    <span className="font-mono text-blue-600 font-medium">{key}</span>
                    <span className="ml-2 text-gray-800">{summary}</span>
                  </div>
                  <span
                    className={`px-2 py-0.5 rounded text-xs font-medium shrink-0 ${
                      status === "Done"
                        ? "bg-green-100 text-green-700"
                        : "bg-yellow-100 text-yellow-700"
                    }`}
                  >
                    {status}
                  </span>
                </div>
                <div className="mt-1.5 flex gap-3 text-xs text-gray-500">
                  <TypeBadge type={type} />
                  <PriorityBadge priority={priority} />
                  {storyPoints != null && <span>{storyPoints} pts</span>}
                </div>
              </div>
            );
          })}
        </div>
      </section>

      {/* RAG docs */}
      {evidence.relevant_docs.length > 0 && (
        <section>
          <h3 className="font-semibold text-gray-800 mb-3">
            Relevant Docs (RAG)
          </h3>
          {evidence.relevant_docs.map((d, i) => (
            <div key={i} className="border rounded p-3 mb-2 text-sm">
              <div className="flex justify-between items-center">
                <span className="font-mono text-gray-700">
                  {String(d.doc_path ?? d.path ?? "?")}
                </span>
                <span className="text-gray-400 text-xs">
                  relevance: {Number(d.relevance_score ?? 0).toFixed(3)}
                </span>
              </div>
              {d.section != null && (
                <span className="text-xs text-gray-500">§ {String(d.section)}</span>
              )}
              <p className="text-gray-600 mt-1 text-xs line-clamp-3">
                {String(d.content ?? "").slice(0, 200)}
                {String(d.content ?? "").length > 200 ? "…" : ""}
              </p>
            </div>
          ))}
        </section>
      )}
    </div>
  );
}

function CodeInsightSection({ items }: { items: CodeInsight[] }) {
  const changeTypeBg: Record<string, string> = {
    added: "bg-green-100 text-green-700",
    deleted: "bg-red-100 text-red-700",
    security: "bg-red-100 text-red-700",
    migration: "bg-yellow-100 text-yellow-700",
    config: "bg-gray-100 text-gray-600",
    modified: "bg-purple-100 text-purple-700",
  };
  return (
    <div className="rounded border p-3 bg-purple-50 border-purple-100">
      <p className="text-xs font-semibold uppercase mb-2 text-purple-700">Code Insights</p>
      <ul className="space-y-2">
        {items.map((item, i) => (
          <li key={i} className="text-sm flex gap-2 items-start">
            <span
              className={`shrink-0 text-xs font-mono px-1 rounded mt-0.5 ${
                item.verified ? "bg-green-100 text-green-700" : "bg-yellow-100 text-yellow-700"
              }`}
            >
              {item.verified ? "verified" : "unverified"}
            </span>
            <div className="min-w-0">
              <div className="flex flex-wrap items-center gap-1.5 mb-0.5">
                <span className="font-mono text-xs text-gray-500 break-all">{item.filename}</span>
                <span
                  className={`text-xs px-1 rounded ${
                    changeTypeBg[item.change_type] ?? "bg-gray-100 text-gray-600"
                  }`}
                >
                  {item.change_type}
                </span>
              </div>
              <p className="text-gray-700">{item.observation}</p>
            </div>
          </li>
        ))}
      </ul>
    </div>
  );
}

function DigestSection({
  title,
  items,
  color,
}: {
  title: string;
  items: string[];
  color: "blue" | "orange" | "red" | "purple";
}) {
  const bg = { blue: "bg-blue-50 border-blue-100", orange: "bg-orange-50 border-orange-100", red: "bg-red-50 border-red-100", purple: "bg-purple-50 border-purple-100" };
  const tc = { blue: "text-blue-700", orange: "text-orange-700", red: "text-red-700", purple: "text-purple-700" };
  return (
    <div className={`rounded border p-3 ${bg[color]}`}>
      <p className={`text-xs font-semibold uppercase mb-2 ${tc[color]}`}>{title}</p>
      <ul className="space-y-1">
        {items.map((item, i) => (
          <li key={i} className="text-sm text-gray-700 flex gap-2">
            <span className="shrink-0 text-gray-400">·</span>
            <span>{item}</span>
          </li>
        ))}
      </ul>
    </div>
  );
}

function TypeBadge({ type }: { type: string }) {
  const c: Record<string, string> = { Story: "bg-blue-100 text-blue-700", Bug: "bg-red-100 text-red-700", Task: "bg-gray-100 text-gray-700", Epic: "bg-purple-100 text-purple-700" };
  return <span className={`px-1.5 py-0.5 rounded ${c[type] ?? "bg-gray-100 text-gray-600"}`}>{type}</span>;
}

function PriorityBadge({ priority }: { priority: string }) {
  const c: Record<string, string> = { Highest: "text-red-600 font-semibold", High: "text-orange-600", Medium: "text-yellow-600", Low: "text-gray-500" };
  return <span className={c[priority] ?? "text-gray-500"}>{priority}</span>;
}

function EvaluationPanel({
  evaluation,
  review,
  digest,
}: {
  evaluation: Release["evaluation"];
  review: Record<string, unknown>;
  digest: Record<string, unknown>;
}) {
  const aiApproved = review.approved as boolean | undefined;

  return (
    <div className="space-y-6">
      {/* AI approval signal */}
      <div
        className={`rounded-lg border p-4 ${
          aiApproved
            ? "bg-green-50 border-green-200"
            : "bg-yellow-50 border-yellow-200"
        }`}
      >
        <p className="font-semibold text-sm">
          {aiApproved
            ? "✅ AI reviewer: content looks good"
            : "⚠️ AI reviewer: flagged issues — check below"}
        </p>
        <p className="text-xs text-gray-600 mt-1">
          This is the AI&apos;s assessment only. A human must still review and approve.
        </p>
      </div>

      {/* Metrics grid */}
      <div className="grid grid-cols-2 gap-4">
        <MetricCard
          label="Overall Score"
          value={`${(evaluation.overall_score * 100).toFixed(0)}%`}
          color={evaluation.overall_score >= 0.7 ? "green" : "yellow"}
        />
        <MetricCard
          label="Hallucination Rate"
          value={`${(evaluation.hallucination_rate * 100).toFixed(0)}%`}
          color={evaluation.hallucination_rate <= 0.1 ? "green" : "red"}
        />
        <MetricCard
          label="Ticket Coverage"
          value={`${(evaluation.ticket_coverage * 100).toFixed(0)}%`}
          color={evaluation.ticket_coverage >= 0.8 ? "green" : "yellow"}
        />
        <MetricCard
          label="Doc Accuracy"
          value={`${(evaluation.doc_recommendation_accuracy * 100).toFixed(0)}%`}
          color={evaluation.doc_recommendation_accuracy >= 0.7 ? "green" : "yellow"}
        />
      </div>

      {/* Reviewer detail */}
      <section>
        <h3 className="font-medium mb-2">Reviewer Details (score: {String(review.overall_score ?? "—")}/10)</h3>
        <div className="bg-gray-50 rounded p-4 text-sm space-y-3">
          {Array.isArray(review.hallucination_issues) &&
            (review.hallucination_issues as unknown[]).length > 0 && (
              <div>
                <p className="font-semibold text-red-600 mb-1">Hallucination Issues</p>
                <ul className="space-y-1 list-disc ml-4">
                  {(
                    review.hallucination_issues as Array<{ text: string; reason: string }>
                  ).map((h, i) => (
                    <li key={i} className="text-red-700">
                      <span className="italic">&ldquo;{h.text}&rdquo;</span> — {h.reason}
                    </li>
                  ))}
                </ul>
              </div>
            )}
          {Array.isArray(review.missing_coverage) &&
            (review.missing_coverage as unknown[]).length > 0 && (
              <div>
                <p className="font-semibold text-yellow-700 mb-1">Missing Coverage</p>
                <ul className="space-y-1 list-disc ml-4">
                  {(
                    review.missing_coverage as Array<{ item: string; source: string }>
                  ).map((m, i) => (
                    <li key={i}>
                      {m.item}{" "}
                      <span className="text-gray-500">(source: {m.source})</span>
                    </li>
                  ))}
                </ul>
              </div>
            )}
          {Array.isArray(review.suggestions) &&
            (review.suggestions as unknown[]).length > 0 && (
              <div>
                <p className="font-semibold text-gray-700 mb-1">Suggestions</p>
                <ul className="space-y-1 list-disc ml-4">
                  {(review.suggestions as string[]).map((s, i) => (
                    <li key={i}>{s}</li>
                  ))}
                </ul>
              </div>
            )}
        </div>
      </section>

      {digest.summary != null && (
        <section>
          <h3 className="font-medium mb-2">Release Summary</h3>
          <p className="text-sm text-gray-700 bg-gray-50 rounded p-3">
            {String(digest.summary)}
          </p>
        </section>
      )}
    </div>
  );
}

function MetricCard({ label, value, color }: { label: string; value: string; color: "green" | "yellow" | "red" }) {
  const c = { green: "border-green-200 bg-green-50", yellow: "border-yellow-200 bg-yellow-50", red: "border-red-200 bg-red-50" };
  return (
    <div className={`border rounded-lg p-4 ${c[color]}`}>
      <p className="text-sm text-gray-600">{label}</p>
      <p className="text-2xl font-semibold mt-1">{value}</p>
    </div>
  );
}

function StatusBadge({ status }: { status: string }) {
  const c: Record<string, string> = {
    review: "bg-blue-100 text-blue-800",
    approved: "bg-green-100 text-green-800",
    rejected: "bg-red-100 text-red-800",
    needs_revision: "bg-orange-100 text-orange-800",
  };
  return (
    <span className={`px-2 py-1 rounded-full text-xs font-medium ${c[status] || "bg-gray-100"}`}>
      {status === "review" ? "Pending Review" : status.replace("_", " ")}
    </span>
  );
}
