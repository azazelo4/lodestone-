import { useCallback, useEffect, useState } from "react";
import { useSearchParams } from "react-router-dom";
import { api, Issue } from "../api";
import IssueList from "../components/IssueList";
import IssuePanel from "../components/IssuePanel";
import { useT } from "../i18n";

export default function MyWork() {
  const { t } = useT();
  const [issues, setIssues] = useState<Issue[] | null>(null);
  const [params, setParams] = useSearchParams();
  const load = useCallback(() => api.myIssues().then(setIssues), []);
  useEffect(() => { load(); }, [load]);
  const openKey = params.get("issue");
  return (
    <>
      <div className="topbar"><h1>{t("my.title")}</h1></div>
      <div className="content">
        <div className="page" style={{ maxWidth: "none" }}>
          <p className="sub">{t("my.sub")}</p>
          {issues && (issues.length ? <IssueList issues={issues} showProject onOpen={(k) => setParams({ issue: k })} />
            : <div className="empty">{t("my.empty")}</div>)}
        </div>
      </div>
      {openKey && <IssuePanel issueKey={openKey} onClose={() => setParams({})} onChanged={load} onOpen={(k) => setParams({ issue: k })} />}
    </>
  );
}
