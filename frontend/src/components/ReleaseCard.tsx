"use client";

import { useState } from "react";
import ReactMarkdown from "react-markdown";

interface DocUpdate {
  doc_path: string;
  section: string;
  suggested_content: string;
  action: string;
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

export function ReleaseCard({ release, onApprove, onBack }: Props) {
  const [activeTab, setActiveTab] = useState<TabKey>("changelog");
  const [editing, setEditing] = useState(false);
  const [editedChangelog, setEditedChangelog] = useState(release.artifacts.changelog);
  const [editedInternal, setEditedInternal] = useState(release.artifacts.internal_release_notes);
  const [editedCustomer, setEditedCustomer] = useState(release.artifacts.customer_release_notes);

  const tabs: { key: TabKey; label: string }[] = [
    { key: "changelog", label: "Changelog" },
    { key: "internal", label: "Internal Notes" },
    { key: "customer", label: "Customer Notes" },
    { key: "docs", label: "Doc Updates" },
    { key: "evidence", label: "Source Evidence" },
    { key: "evaluation", label: "Evaluation" },
  ];

  const handleApprove = () => {
    onApprove(release.id, {
      changelog: editedChangelog,
      internal_release_notes: editedInternal,
      customer_release_notes: editedCustomer,
    });
    setEditing(false);
  };

  return (
    <div className="bg-white rounded-lg border">
      {/* Header */}
      <div className="p-4 border-b flex items-center justify-between">
        <div className="flex items-center gap-3">
          <button onClick={onBack} className="text-gray-500 hover:text-gray-700">
            ← Back
          </button>
          <h2 className="text-lg font-medium">{release.name}</h2>
          <StatusBadge status={release.status} />
        </div>
        <div className="flex gap-2">
          {release.status !== "approved" && (
            <>
              <button
                onClick={() => setEditing(!editing)}
                className="px-3 py-1.5 text-sm border rounded-md hover:bg-gray-50"
              >
                {editing ? "Cancel Edit" : "Edit"}
              </button>
              <button
                onClick={handleApprove}
                className="px-3 py-1.5 text-sm bg-green-600 text-white rounded-md hover:bg-green-700"
              >
                Approve
              </button>
            </>
          )}
        </div>
      </div>

      {/* Tabs */}
      <div className="border-b px-4">
        <nav className="flex gap-4">
          {tabs.map((tab) => (
            <button
              key={tab.key}
              onClick={() => setActiveTab(tab.key)}
              className={`py-3 text-sm font-medium border-b-2 transition ${
                activeTab === tab.key
                  ? "border-blue-500 text-blue-600"
                  : "border-transparent text-gray-500 hover:text-gray-700"
              }`}
            >
              {tab.label}
            </button>
          ))}
        </nav>
      </div>

      {/* Content */}
      <div className="p-6">
        {activeTab === "changelog" && (
          <MarkdownPanel
            content={editedChangelog}
            editing={editing}
            onChange={setEditedChangelog}
          />
        )}
        {activeTab === "internal" && (
          <MarkdownPanel
            content={editedInternal}
            editing={editing}
            onChange={setEditedInternal}
          />
        )}
        {activeTab === "customer" && (
          <MarkdownPanel
            content={editedCustomer}
            editing={editing}
            onChange={setEditedCustomer}
          />
        )}
        {activeTab === "docs" && (
          <DocUpdatesPanel updates={release.artifacts.documentation_updates} />
        )}
        {activeTab === "evidence" && (
          <EvidencePanel evidence={release.source_evidence} />
        )}
        {activeTab === "evaluation" && (
          <EvaluationPanel
            evaluation={release.evaluation}
            review={release.review}
          />
        )}
      </div>
    </div>
  );
}

function MarkdownPanel({
  content,
  editing,
  onChange,
}: {
  content: string;
  editing: boolean;
  onChange: (v: string) => void;
}) {
  if (editing) {
    return (
      <textarea
        value={content}
        onChange={(e) => onChange(e.target.value)}
        className="w-full h-96 font-mono text-sm p-3 border rounded-md focus:outline-none focus:ring-2 focus:ring-blue-500"
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
            <span className={`px-2 py-0.5 rounded text-xs font-medium ${
              u.action === "add" ? "bg-green-100 text-green-700" :
              u.action === "update" ? "bg-yellow-100 text-yellow-700" :
              "bg-blue-100 text-blue-700"
            }`}>
              {u.action}
            </span>
            <span className="font-mono text-sm text-gray-700">{u.doc_path}</span>
            {u.section && (
              <span className="text-sm text-gray-500">→ {u.section}</span>
            )}
          </div>
          <div className="bg-gray-50 rounded p-3 text-sm">
            <ReactMarkdown>{u.suggested_content}</ReactMarkdown>
          </div>
        </div>
      ))}
    </div>
  );
}

function EvidencePanel({ evidence }: { evidence: Release["source_evidence"] }) {
  return (
    <div className="space-y-6">
      <section>
        <h3 className="font-medium mb-2">Commits ({evidence.commits.length})</h3>
        <div className="space-y-2">
          {evidence.commits.map((c: Record<string, unknown>, i: number) => (
            <div key={i} className="text-sm font-mono bg-gray-50 rounded p-2">
              <span className="text-blue-600">{String(c.sha).slice(0, 7)}</span>{" "}
              {String(c.message)}
            </div>
          ))}
        </div>
      </section>
      <section>
        <h3 className="font-medium mb-2">Pull Requests ({evidence.pull_requests.length})</h3>
        {evidence.pull_requests.map((pr: Record<string, unknown>, i: number) => (
          <div key={i} className="border rounded p-3 mb-2">
            <span className="font-medium">#{String(pr.id)}</span> {String(pr.title)}
            <span className="ml-2 text-xs text-gray-500">by {String(pr.author)}</span>
          </div>
        ))}
      </section>
      <section>
        <h3 className="font-medium mb-2">Jira Tickets ({evidence.tickets.length})</h3>
        {evidence.tickets.map((t: Record<string, unknown>, i: number) => (
          <div key={i} className="border rounded p-3 mb-2">
            <span className="font-mono text-blue-600">{String(t.key)}</span>{" "}
            {String(t.summary)}
            <span className="ml-2 text-xs text-gray-500">{String(t.type)} / {String(t.priority)}</span>
          </div>
        ))}
      </section>
      <section>
        <h3 className="font-medium mb-2">Relevant Docs (RAG)</h3>
        {evidence.relevant_docs.map((d: Record<string, unknown>, i: number) => (
          <div key={i} className="border rounded p-3 mb-2 text-sm">
            <div className="flex justify-between">
              <span className="font-mono">{String(d.doc_path)}</span>
              <span className="text-gray-500">
                relevance: {Number(d.relevance_score).toFixed(3)}
              </span>
            </div>
            <p className="text-gray-600 mt-1 line-clamp-2">{String(d.content).slice(0, 150)}...</p>
          </div>
        ))}
      </section>
    </div>
  );
}

function EvaluationPanel({
  evaluation,
  review,
}: {
  evaluation: Release["evaluation"];
  review: Record<string, unknown>;
}) {
  return (
    <div className="space-y-6">
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

      <section>
        <h3 className="font-medium mb-2">Reviewer Assessment</h3>
        <div className="bg-gray-50 rounded p-4 text-sm">
          <p>
            <strong>Score:</strong> {String(review.overall_score)}/10
          </p>
          <p>
            <strong>Approved:</strong> {review.approved ? "Yes" : "No"}
          </p>
          {Array.isArray(review.suggestions) && review.suggestions.length > 0 && (
            <div className="mt-2">
              <strong>Suggestions:</strong>
              <ul className="list-disc ml-4 mt-1">
                {(review.suggestions as string[]).map((s, i) => (
                  <li key={i}>{s}</li>
                ))}
              </ul>
            </div>
          )}
        </div>
      </section>
    </div>
  );
}

function MetricCard({
  label,
  value,
  color,
}: {
  label: string;
  value: string;
  color: "green" | "yellow" | "red";
}) {
  const colors = {
    green: "border-green-200 bg-green-50",
    yellow: "border-yellow-200 bg-yellow-50",
    red: "border-red-200 bg-red-50",
  };
  return (
    <div className={`border rounded-lg p-4 ${colors[color]}`}>
      <p className="text-sm text-gray-600">{label}</p>
      <p className="text-2xl font-semibold mt-1">{value}</p>
    </div>
  );
}

function StatusBadge({ status }: { status: string }) {
  const colors: Record<string, string> = {
    review: "bg-yellow-100 text-yellow-800",
    approved: "bg-green-100 text-green-800",
    rejected: "bg-red-100 text-red-800",
    needs_revision: "bg-orange-100 text-orange-800",
  };
  return (
    <span className={`px-2 py-1 rounded-full text-xs font-medium ${colors[status] || "bg-gray-100"}`}>
      {status.replace("_", " ")}
    </span>
  );
}
