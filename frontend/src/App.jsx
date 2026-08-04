import { useEffect, useState } from "react";
import Chat from "./Chat";
import GanttChart from "./GanttChart";
import Toolbar from "./Toolbar";
import { fetchPlan } from "./api";
import "./styles.css";

export default function App() {
  const [plan, setPlan] = useState(null);
  const [messages, setMessages] = useState([]);
  const [loading, setLoading] = useState(false);
  const [offline, setOffline] = useState(false);

  useEffect(() => {
    fetchPlan().then(setPlan).catch(() => setOffline(true));
  }, []);

  return (
    <div className="app">
      <Toolbar plan={plan} onPlan={setPlan} loading={loading} />
      <div className="workspace">
        <main className="chart-pane">
          {offline ? (
            <p className="empty">Бэкенд не отвечает. Запустите его на порту 8000 и обновите страницу.</p>
          ) : plan && plan.tasks.length > 0 ? (
            <GanttChart plan={plan} />
          ) : (
            <p className="empty">План пуст. Загрузите файл Excel или попросите чат добавить задачи.</p>
          )}
        </main>
        <Chat
          messages={messages}
          setMessages={setMessages}
          loading={loading}
          setLoading={setLoading}
          onPlan={setPlan}
        />
      </div>
    </div>
  );
}
