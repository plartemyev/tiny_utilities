<?php
session_start();
?>

<!DOCTYPE html>
<html>
<body>

<?php
$_SESSION["renderCounter"] += 1;
echo "<p>This page was rendered " . $_SESSION["renderCounter"] . " times in this session.</p>";
?>

</body>
</html>
